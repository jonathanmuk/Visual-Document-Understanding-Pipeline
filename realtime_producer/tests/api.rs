//! Integration tests for the producer API.
//!
//! The tests that need a real Redis read its address from `REDIS_URL` and skip
//! themselves when it is not set, so `cargo test` passes on a laptop with no
//! Redis running. CI provides one. The tests that need no Redis always run.

use axum::{
    body::Body,
    http::{header, Request, StatusCode},
};
use ocr_producer_rust::{app, AppState, Config, MAX_FILE_BYTES, QUEUE_KEY};
use redis::AsyncCommands;
use std::collections::HashMap;
use std::sync::Arc;
use tower::ServiceExt;

const BOUNDARY: &str = "vdu-test-boundary";
const PDF: &[u8] = b"%PDF-1.4\n%fake\n";
const PNG: &[u8] = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR";
const JPG: &[u8] = &[0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, b'J', b'F', b'I', b'F'];

struct Part<'a> {
    name: &'a str,
    filename: Option<&'a str>,
    content: &'a [u8],
}

fn multipart(parts: &[Part]) -> Vec<u8> {
    let mut body = Vec::new();
    for p in parts {
        body.extend_from_slice(format!("--{BOUNDARY}\r\n").as_bytes());
        match p.filename {
            Some(f) => body.extend_from_slice(
                format!("Content-Disposition: form-data; name=\"{}\"; filename=\"{}\"\r\n", p.name, f).as_bytes()),
            None => body.extend_from_slice(
                format!("Content-Disposition: form-data; name=\"{}\"\r\n", p.name).as_bytes()),
        }
        body.extend_from_slice(b"Content-Type: application/octet-stream\r\n\r\n");
        body.extend_from_slice(p.content);
        body.extend_from_slice(b"\r\n");
    }
    body.extend_from_slice(format!("--{BOUNDARY}--\r\n").as_bytes());
    body
}

fn file_body(name: &str, filename: Option<&str>, content: &[u8]) -> Vec<u8> {
    multipart(&[Part { name, filename, content }])
}

fn post(body: Vec<u8>, content_length: bool, no_cache: bool) -> Request<Body> {
    let mut b = Request::builder()
        .method("POST")
        .uri("/process")
        .header(header::CONTENT_TYPE, format!("multipart/form-data; boundary={BOUNDARY}"));
    if content_length {
        b = b.header(header::CONTENT_LENGTH, body.len());
    }
    if no_cache {
        b = b.header(header::CACHE_CONTROL, "no-cache");
    }
    b.body(Body::from(body)).unwrap()
}

fn state_with(url: &str, config: Config) -> Arc<AppState> {
    Arc::new(AppState::new(redis::Client::open(url).unwrap(), config))
}

/// Points at an address nothing listens on. Handlers that should not touch
/// Redis must still succeed.
fn no_redis() -> Arc<AppState> {
    state_with("redis://127.0.0.1:1", Config::default())
}

fn redis_url() -> Option<String> {
    std::env::var("REDIS_URL").ok()
}

async fn text(resp: axum::response::Response) -> String {
    String::from_utf8(hyper::body::to_bytes(resp.into_body()).await.unwrap().to_vec()).unwrap()
}

async fn json(resp: axum::response::Response) -> serde_json::Value {
    serde_json::from_str(&text(resp).await).unwrap()
}

async fn get(state: Arc<AppState>, path: &str) -> axum::response::Response {
    app(state).oneshot(Request::get(path).body(Body::empty()).unwrap()).await.unwrap()
}

/// A document unique to one test run, so tests sharing a Redis never collide
/// through the result cache.
fn unique_pdf(tag: &str) -> Vec<u8> {
    format!("%PDF-1.4\n% {tag} {}\n", uuid::Uuid::new_v4()).into_bytes()
}

async fn cleanup(conn: &mut redis::aio::Connection, task_id: &str) {
    let cache: Option<String> = conn.hget(format!("task:{task_id}"), "cache_key").await.unwrap();
    let _: () = conn.del(&[format!("task:{task_id}"), format!("taskdata:{task_id}")]).await.unwrap();
    if let Some(k) = cache {
        let _: () = conn.del(k).await.unwrap();
    }
    let _: () = conn.lrem(QUEUE_KEY, 0, task_id).await.unwrap();
}

// --- No Redis required ---------------------------------------------------------

#[tokio::test]
async fn health_returns_200() {
    assert_eq!(get(no_redis(), "/health").await.status(), StatusCode::OK);
}

#[tokio::test]
async fn ready_returns_503_when_redis_is_unreachable() {
    assert_eq!(get(no_redis(), "/ready").await.status(), StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn metrics_endpoint_serves_prometheus_text() {
    let state = no_redis();
    let _ = get(state.clone(), "/health").await;
    let t = text(get(state, "/metrics").await).await;
    // The registry is process-global and tests run in parallel, so values vary.
    // Presence of every known label set must not.
    assert!(t.contains("vdu_http_requests_total{route=\"/health\",status=\"200\"}"), "{t}");
    for reason in ["no_file", "empty", "too_large", "unsupported_type", "bad_callback"] {
        assert!(t.contains(&format!("vdu_uploads_rejected_total{{reason=\"{reason}\"}}")), "missing {reason}");
    }
    for outcome in ["hit", "dedupe", "miss", "bypass"] {
        assert!(t.contains(&format!("vdu_cache_total{{outcome=\"{outcome}\"}}")), "missing {outcome}");
    }
}

#[tokio::test]
async fn missing_file_field_is_rejected_without_touching_redis() {
    let resp = app(no_redis()).oneshot(post(file_body("not_file", Some("x.pdf"), PDF), true, false)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    assert!(text(resp).await.contains("missing 'file' field"));
}

#[tokio::test]
async fn text_in_the_file_field_is_rejected_with_a_helpful_message() {
    // What `curl -F "file=C:\path\doc.pdf"` (no @) actually sends.
    let resp = app(no_redis()).oneshot(post(file_body("file", None, b"C:\\Users\\me\\doc.pdf"), true, false)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    assert!(text(resp).await.contains("file=@path"));
}

#[tokio::test]
async fn empty_file_is_rejected() {
    let resp = app(no_redis()).oneshot(post(file_body("file", Some("e.pdf"), b""), true, false)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    assert!(text(resp).await.contains("empty"));
}

#[tokio::test]
async fn unsupported_content_is_rejected_with_415_even_if_named_pdf() {
    let resp = app(no_redis()).oneshot(post(file_body("file", Some("looks.pdf"), b"just text"), true, false)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNSUPPORTED_MEDIA_TYPE);
    assert!(text(resp).await.contains("PDF, PNG, or JPEG"));
}

#[tokio::test]
async fn one_byte_over_the_file_limit_gets_413_from_the_handler() {
    // Body fits under the body limit, file is one byte too big: the handler's
    // own check answers, with the exact sizes in the message.
    let mut big = b"%PDF-".to_vec();
    big.resize(MAX_FILE_BYTES + 1, b'x');
    let resp = app(no_redis()).oneshot(post(file_body("file", Some("big.pdf"), &big), true, false)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::PAYLOAD_TOO_LARGE);
    assert!(text(resp).await.contains(&MAX_FILE_BYTES.to_string()));
}

#[tokio::test]
async fn far_over_the_limit_with_content_length_gets_413_from_the_body_layer() {
    let big = vec![b'x'; MAX_FILE_BYTES + 200 * 1024];
    let resp = app(no_redis()).oneshot(post(file_body("file", Some("big.pdf"), &big), true, false)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::PAYLOAD_TOO_LARGE);
}

#[tokio::test]
async fn far_over_the_limit_without_content_length_is_still_rejected() {
    // A streaming client that declares no length. The body layer stops it; the
    // code is the extractor's generic 400. Never accepted.
    let big = vec![b'x'; MAX_FILE_BYTES + 200 * 1024];
    let resp = app(no_redis()).oneshot(post(file_body("file", Some("big.pdf"), &big), false, false)).await.unwrap();
    assert!(resp.status().is_client_error(), "got {}", resp.status());
}

#[tokio::test]
async fn callback_is_refused_when_callbacks_are_off() {
    let body = multipart(&[
        Part { name: "file", filename: Some("a.pdf"), content: PDF },
        Part { name: "callback_url", filename: None, content: b"https://hooks.example.com/x" },
    ]);
    let resp = app(no_redis()).oneshot(post(body, true, false)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    assert!(text(resp).await.contains("not enabled"));
}

#[tokio::test]
async fn non_multipart_request_is_rejected() {
    let req = Request::builder().method("POST").uri("/process")
        .header(header::CONTENT_TYPE, "application/json").body(Body::from("{}")).unwrap();
    assert!(app(no_redis()).oneshot(req).await.unwrap().status().is_client_error());
}

#[tokio::test]
async fn unknown_route_is_404() {
    assert_eq!(get(no_redis(), "/nope").await.status(), StatusCode::NOT_FOUND);
}

// --- Redis required (skipped when REDIS_URL is unset) ------------------------

macro_rules! need_redis {
    () => {
        match redis_url() {
            Some(u) => u,
            None => { eprintln!("REDIS_URL not set; skipping"); return; }
        }
    };
}

async fn submit(state: &Arc<AppState>, content: &[u8], no_cache: bool) -> (StatusCode, serde_json::Value) {
    let resp = app(state.clone()).oneshot(post(file_body("file", Some("doc.pdf"), content), true, no_cache)).await.unwrap();
    let code = resp.status();
    (code, json(resp).await)
}

#[tokio::test]
async fn ready_returns_200_when_redis_answers() {
    let url = need_redis!();
    assert_eq!(get(state_with(&url, Config::default()), "/ready").await.status(), StatusCode::OK);
}

#[tokio::test]
async fn unknown_task_id_returns_404() {
    let url = need_redis!();
    let resp = get(state_with(&url, Config::default()), "/status/00000000-0000-0000-0000-000000000000").await;
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn submit_stores_raw_bytes_separately_with_expiry() {
    let url = need_redis!();
    let state = state_with(&url, Config::default());
    let doc = unique_pdf("raw");
    let (code, body) = submit(&state, &doc, false).await;
    assert_eq!(code, StatusCode::ACCEPTED);
    assert_eq!(body["status"], "queued");
    assert!(body.get("cached").is_none(), "only present when true");
    let id = body["task_id"].as_str().unwrap().to_string();

    let mut conn = redis::Client::open(url.as_str()).unwrap().get_async_connection().await.unwrap();
    let hash: HashMap<String, String> = conn.hgetall(format!("task:{id}")).await.unwrap();
    assert_eq!(hash["status"], "queued");
    assert_eq!(hash["attempts"], "0");
    assert_eq!(hash["extension"], "pdf");
    assert!(!hash.contains_key("data"), "the document must not live in the task hash");
    assert!(hash["cache_key"].starts_with("cache:1:default:"));

    let stored: Vec<u8> = conn.get(format!("taskdata:{id}")).await.unwrap();
    assert_eq!(stored, doc, "raw bytes, not base64");
    let ttl: i64 = conn.ttl(format!("taskdata:{id}")).await.unwrap();
    assert!(ttl > 0 && ttl <= 172_800, "document must expire, got ttl {ttl}");
    let ttl: i64 = conn.ttl(format!("task:{id}")).await.unwrap();
    assert!(ttl > 0, "unfinished task must expire eventually");

    let queued: Vec<String> = conn.lrange(QUEUE_KEY, 0, -1).await.unwrap();
    assert!(queued.contains(&id));

    let st = json(get(state.clone(), &format!("/status/{id}")).await).await;
    assert_eq!(st["status"], "queued");
    assert_eq!(st["attempts"], 0);
    assert!(st.get("callback_status").is_none());
    cleanup(&mut conn, &id).await;
}

#[tokio::test]
async fn identical_document_waiting_is_joined_not_repeated() {
    let url = need_redis!();
    let state = state_with(&url, Config::default());
    let doc = unique_pdf("dedupe");
    let (_, first) = submit(&state, &doc, false).await;
    let (code, second) = submit(&state, &doc, false).await;
    assert_eq!(code, StatusCode::ACCEPTED);
    assert_eq!(second["task_id"], first["task_id"]);
    assert_eq!(second["deduplicated"], true);
    let id = first["task_id"].as_str().unwrap().to_string();
    let mut conn = redis::Client::open(url.as_str()).unwrap().get_async_connection().await.unwrap();
    let queued: Vec<String> = conn.lrange(QUEUE_KEY, 0, -1).await.unwrap();
    assert_eq!(queued.iter().filter(|q| **q == id).count(), 1, "queued once, not twice");
    cleanup(&mut conn, &id).await;
}

#[tokio::test]
async fn identical_document_already_done_is_served_from_cache() {
    let url = need_redis!();
    let state = state_with(&url, Config::default());
    let doc = unique_pdf("hit");
    let (_, first) = submit(&state, &doc, false).await;
    let id = first["task_id"].as_str().unwrap().to_string();
    let mut conn = redis::Client::open(url.as_str()).unwrap().get_async_connection().await.unwrap();
    let _: () = conn.hset(format!("task:{id}"), "status", "done").await.unwrap();

    let (code, second) = submit(&state, &doc, false).await;
    assert_eq!(code, StatusCode::OK, "a cached answer is 200, not 202");
    assert_eq!(second["task_id"], first["task_id"]);
    assert_eq!(second["status"], "done");
    assert_eq!(second["cached"], true);
    cleanup(&mut conn, &id).await;
}

#[tokio::test]
async fn no_cache_header_forces_a_new_task() {
    let url = need_redis!();
    let state = state_with(&url, Config::default());
    let doc = unique_pdf("fresh");
    let (_, first) = submit(&state, &doc, false).await;
    let (code, second) = submit(&state, &doc, true).await;
    assert_eq!(code, StatusCode::ACCEPTED);
    assert_ne!(second["task_id"], first["task_id"]);
    let mut conn = redis::Client::open(url.as_str()).unwrap().get_async_connection().await.unwrap();
    for id in [&first["task_id"], &second["task_id"]] {
        cleanup(&mut conn, id.as_str().unwrap()).await;
    }
}

#[tokio::test]
async fn failed_cached_task_is_not_reused() {
    let url = need_redis!();
    let state = state_with(&url, Config::default());
    let doc = unique_pdf("failed");
    let (_, first) = submit(&state, &doc, false).await;
    let id = first["task_id"].as_str().unwrap().to_string();
    let mut conn = redis::Client::open(url.as_str()).unwrap().get_async_connection().await.unwrap();
    let _: () = conn.hset(format!("task:{id}"), "status", "failed").await.unwrap();
    let (code, second) = submit(&state, &doc, false).await;
    assert_eq!(code, StatusCode::ACCEPTED);
    assert_ne!(second["task_id"], first["task_id"], "a failure must be retried, not replayed");
    cleanup(&mut conn, &id).await;
    cleanup(&mut conn, second["task_id"].as_str().unwrap()).await;
}

#[tokio::test]
async fn cache_can_be_switched_off() {
    let url = need_redis!();
    let state = state_with(&url, Config { result_cache: false, ..Config::default() });
    let doc = unique_pdf("off");
    let (_, a) = submit(&state, &doc, false).await;
    let (_, b) = submit(&state, &doc, false).await;
    assert_ne!(a["task_id"], b["task_id"]);
    let mut conn = redis::Client::open(url.as_str()).unwrap().get_async_connection().await.unwrap();
    let hash: HashMap<String, String> = conn.hgetall(format!("task:{}", a["task_id"].as_str().unwrap())).await.unwrap();
    assert!(!hash.contains_key("cache_key"));
    for id in [&a["task_id"], &b["task_id"]] {
        cleanup(&mut conn, id.as_str().unwrap()).await;
    }
}

#[tokio::test]
async fn a_file_of_exactly_the_limit_is_accepted() {
    let url = need_redis!();
    let state = state_with(&url, Config::default());
    let mut doc = unique_pdf("exact");
    doc.resize(MAX_FILE_BYTES, b'x');
    let (code, body) = submit(&state, &doc, true).await;
    assert_eq!(code, StatusCode::ACCEPTED, "exactly {MAX_FILE_BYTES} bytes must be allowed");
    let mut conn = redis::Client::open(url.as_str()).unwrap().get_async_connection().await.unwrap();
    let stored: Vec<u8> = conn.get(format!("taskdata:{}", body["task_id"].as_str().unwrap())).await.unwrap();
    assert_eq!(stored.len(), MAX_FILE_BYTES);
    cleanup(&mut conn, body["task_id"].as_str().unwrap()).await;
}

#[tokio::test]
async fn corrupt_but_correctly_typed_file_is_accepted_and_left_to_the_worker() {
    // The API checks the type, not the whole structure. A file with a valid PDF
    // header and garbage after it is queued; the worker's pre-flight check opens
    // it, fails it with a reason, and never spends GPU time on it.
    let url = need_redis!();
    let state = state_with(&url, Config::default());
    let mut doc = b"%PDF-1.7\n".to_vec();
    doc.extend_from_slice(&uuid::Uuid::new_v4().as_bytes()[..]);
    doc.extend_from_slice(&[0u8; 512]);
    let (code, body) = submit(&state, &doc, true).await;
    assert_eq!(code, StatusCode::ACCEPTED);
    let mut conn = redis::Client::open(url.as_str()).unwrap().get_async_connection().await.unwrap();
    cleanup(&mut conn, body["task_id"].as_str().unwrap()).await;
}

#[tokio::test]
async fn allowed_callback_is_stored_and_bypasses_the_cache() {
    let url = need_redis!();
    let cfg = Config {
        callback_allowed_hosts: vec!["hooks.example.com".into()],
        ..Config::default()
    };
    let state = state_with(&url, cfg);
    let doc = unique_pdf("cb");
    let (_, plain) = submit(&state, &doc, false).await;
    let body = multipart(&[
        Part { name: "callback_url", filename: None, content: b"https://hooks.example.com/done" },
        Part { name: "file", filename: Some("a.pdf"), content: &doc },
    ]);
    let resp = app(state.clone()).oneshot(post(body, true, false)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);
    let with_cb = json(resp).await;
    assert_ne!(with_cb["task_id"], plain["task_id"], "a callback request gets its own task so its callback fires");
    let mut conn = redis::Client::open(url.as_str()).unwrap().get_async_connection().await.unwrap();
    let stored: String = conn.hget(format!("task:{}", with_cb["task_id"].as_str().unwrap()), "callback_url").await.unwrap();
    assert_eq!(stored, "https://hooks.example.com/done");
    for id in [&plain["task_id"], &with_cb["task_id"]] {
        cleanup(&mut conn, id.as_str().unwrap()).await;
    }
}

#[tokio::test]
async fn disallowed_callback_host_is_refused_before_anything_is_stored() {
    let url = need_redis!();
    let cfg = Config { callback_allowed_hosts: vec!["hooks.example.com".into()], ..Config::default() };
    let body = multipart(&[
        Part { name: "file", filename: Some("a.pdf"), content: PDF },
        Part { name: "callback_url", filename: None, content: b"https://ocr-redis-service:6379/" },
    ]);
    let resp = app(state_with(&url, cfg)).oneshot(post(body, true, false)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    assert!(text(resp).await.contains("not in the allowed list"));
}

#[tokio::test]
async fn stored_extension_comes_from_content_not_filename() {
    let url = need_redis!();
    let state = state_with(&url, Config::default());
    let mut conn = redis::Client::open(url.as_str()).unwrap().get_async_connection().await.unwrap();
    for (name, content, expect) in [("scan.jpg", PDF, "pdf"), ("photo.pdf", JPG, "jpg"), ("noext", PNG, "png")] {
        let body = file_body("file", Some(name), content);
        let resp = app(state.clone()).oneshot(post(body, true, true)).await.unwrap();
        let id = json(resp).await["task_id"].as_str().unwrap().to_string();
        let hash: HashMap<String, String> = conn.hgetall(format!("task:{id}")).await.unwrap();
        assert_eq!(hash["extension"], expect, "{name}");
        assert_eq!(hash["filename"], name, "original name is kept for the user");
        cleanup(&mut conn, &id).await;
    }
}
