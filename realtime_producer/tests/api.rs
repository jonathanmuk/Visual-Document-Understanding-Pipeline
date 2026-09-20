//! Integration tests for the producer API.
//!
//! The tests that need a real Redis read its address from `REDIS_URL` and skip
//! themselves when it is not set, so `cargo test` passes on a laptop with no
//! Redis running. CI provides one. The tests that need no Redis always run.

use axum::{
    body::Body,
    http::{header, Request, StatusCode},
};
use ocr_producer_rust::{app, AppState, MAX_UPLOAD_BYTES, QUEUE_KEY};
use std::sync::Arc;
use tower::ServiceExt;

const BOUNDARY: &str = "vus-test-boundary";
const PDF: &[u8] = b"%PDF-1.4\n%fake\n";
const PNG: &[u8] = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR";
const JPG: &[u8] = &[0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, b'J', b'F', b'I', b'F'];

fn multipart_body(field: &str, filename: Option<&str>, content: &[u8]) -> Vec<u8> {
    let mut body = Vec::new();
    body.extend_from_slice(format!("--{}\r\n", BOUNDARY).as_bytes());
    match filename {
        Some(name) => body.extend_from_slice(
            format!(
                "Content-Disposition: form-data; name=\"{}\"; filename=\"{}\"\r\n",
                field, name
            )
            .as_bytes(),
        ),
        None => body.extend_from_slice(
            format!("Content-Disposition: form-data; name=\"{}\"\r\n", field).as_bytes(),
        ),
    }
    body.extend_from_slice(b"Content-Type: application/octet-stream\r\n\r\n");
    body.extend_from_slice(content);
    body.extend_from_slice(format!("\r\n--{}--\r\n", BOUNDARY).as_bytes());
    body
}

fn post_process(body: Vec<u8>, with_content_length: bool) -> Request<Body> {
    let mut builder = Request::builder()
        .method("POST")
        .uri("/process")
        .header(
            header::CONTENT_TYPE,
            format!("multipart/form-data; boundary={}", BOUNDARY),
        );
    if with_content_length {
        builder = builder.header(header::CONTENT_LENGTH, body.len());
    }
    builder.body(Body::from(body)).unwrap()
}

fn test_state(redis_url: &str) -> Arc<AppState> {
    Arc::new(AppState {
        redis_client: redis::Client::open(redis_url).unwrap(),
    })
}

/// A client pointed at an address nothing listens on. Handlers that touch Redis
/// would fail; handlers that should not touch Redis must still succeed.
fn no_redis_state() -> Arc<AppState> {
    test_state("redis://127.0.0.1:1")
}

fn redis_url() -> Option<String> {
    std::env::var("REDIS_URL").ok()
}

async fn body_string(resp: axum::response::Response) -> String {
    let bytes = hyper::body::to_bytes(resp.into_body()).await.unwrap();
    String::from_utf8(bytes.to_vec()).unwrap()
}

async fn get(state: Arc<AppState>, path: &str) -> axum::response::Response {
    app(state)
        .oneshot(Request::get(path).body(Body::empty()).unwrap())
        .await
        .unwrap()
}

// --- No Redis required ---------------------------------------------------------

#[tokio::test]
async fn health_returns_200() {
    assert_eq!(get(no_redis_state(), "/health").await.status(), StatusCode::OK);
}

#[tokio::test]
async fn ready_returns_503_when_redis_is_unreachable() {
    let resp = get(no_redis_state(), "/ready").await;
    assert_eq!(resp.status(), StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn metrics_endpoint_serves_prometheus_text() {
    let state = no_redis_state();
    // One request first, so the request counter has something to show.
    let _ = get(state.clone(), "/health").await;
    let resp = get(state, "/metrics").await;
    assert_eq!(resp.status(), StatusCode::OK);
    let text = body_string(resp).await;
    // The registry is process-global and tests run in parallel, so the exact
    // count depends on which other tests have hit /health. Presence is enough.
    assert!(text.contains("vus_http_requests_total{route=\"/health\",status=\"200\"}"), "got: {}", text);
    // Every known label set is present from startup, whatever other tests have
    // done in this process (values vary; presence must not).
    for reason in ["no_file", "empty", "unsupported_type"] {
        assert!(text.contains(&format!("vus_uploads_rejected_total{{reason=\"{}\"}}", reason)), "missing reason {}: {}", reason, text);
    }
    for kind in ["pdf", "png", "jpg"] {
        assert!(text.contains(&format!("vus_upload_bytes_count{{type=\"{}\"}}", kind)), "missing type {}: {}", kind, text);
    }
}

#[tokio::test]
async fn missing_file_field_is_rejected_without_touching_redis() {
    let body = multipart_body("not_file", Some("x.pdf"), PDF);
    let resp = app(no_redis_state()).oneshot(post_process(body, true)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    assert!(body_string(resp).await.contains("missing 'file' field"));
}

#[tokio::test]
async fn text_in_the_file_field_is_rejected_with_a_helpful_message() {
    // What `curl -F "file=C:\path\doc.pdf"` (no @) actually sends.
    let body = multipart_body("file", None, b"C:\\Users\\me\\doc.pdf");
    let resp = app(no_redis_state()).oneshot(post_process(body, true)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    let text = body_string(resp).await;
    assert!(text.contains("file=@path"), "message should tell the user about @: {}", text);
}

#[tokio::test]
async fn empty_file_is_rejected() {
    let body = multipart_body("file", Some("empty.pdf"), b"");
    let resp = app(no_redis_state()).oneshot(post_process(body, true)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    assert!(body_string(resp).await.contains("empty"));
}

#[tokio::test]
async fn unsupported_content_is_rejected_with_415_even_if_named_pdf() {
    let body = multipart_body("file", Some("looks-like.pdf"), b"just some text, not a document");
    let resp = app(no_redis_state()).oneshot(post_process(body, true)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNSUPPORTED_MEDIA_TYPE);
    assert!(body_string(resp).await.contains("PDF, PNG, or JPEG"));
}

#[tokio::test]
async fn oversized_upload_with_content_length_gets_413() {
    // What every ordinary client (curl -F, browsers, requests) sends. The body
    // limit layer answers 413 from the declared length, before any handler runs.
    let oversized = vec![b'x'; MAX_UPLOAD_BYTES + 1024];
    let body = multipart_body("file", Some("big.pdf"), &oversized);
    let resp = app(no_redis_state()).oneshot(post_process(body, true)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::PAYLOAD_TOO_LARGE);
}

#[tokio::test]
async fn oversized_upload_without_content_length_is_still_rejected() {
    // A streaming client that declares no length. The body limit layer still
    // stops it; the code is the extractor's generic 400. Never accepted.
    let oversized = vec![b'x'; MAX_UPLOAD_BYTES + 1024];
    let body = multipart_body("file", Some("big.pdf"), &oversized);
    let resp = app(no_redis_state()).oneshot(post_process(body, false)).await.unwrap();
    assert_ne!(resp.status(), StatusCode::ACCEPTED);
    assert!(resp.status().is_client_error());
}

#[tokio::test]
async fn non_multipart_request_is_rejected() {
    let req = Request::builder()
        .method("POST")
        .uri("/process")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from("{}"))
        .unwrap();
    let resp = app(no_redis_state()).oneshot(req).await.unwrap();
    assert!(resp.status().is_client_error(), "got {}", resp.status());
}

#[tokio::test]
async fn unknown_route_is_404() {
    assert_eq!(get(no_redis_state(), "/nope").await.status(), StatusCode::NOT_FOUND);
}

// --- Redis required (skipped when REDIS_URL is unset) ------------------------

#[tokio::test]
async fn ready_returns_200_when_redis_answers() {
    let Some(url) = redis_url() else {
        eprintln!("REDIS_URL not set; skipping");
        return;
    };
    assert_eq!(get(test_state(&url), "/ready").await.status(), StatusCode::OK);
}

#[tokio::test]
async fn unknown_task_id_returns_404() {
    let Some(url) = redis_url() else {
        eprintln!("REDIS_URL not set; skipping");
        return;
    };
    let resp = get(test_state(&url), "/status/00000000-0000-0000-0000-000000000000").await;
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

async fn submit_and_inspect(
    url: &str,
    filename: &str,
    content: &[u8],
) -> (String, std::collections::HashMap<String, String>) {
    let state = test_state(url);
    let body = multipart_body("file", Some(filename), content);
    let resp = app(state.clone()).oneshot(post_process(body, true)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED, "{}", filename);
    let submitted: serde_json::Value = serde_json::from_str(&body_string(resp).await).unwrap();
    let task_id = submitted["task_id"].as_str().unwrap().to_string();

    let mut conn = state.redis_client.get_async_connection().await.unwrap();
    let stored: std::collections::HashMap<String, String> =
        redis::AsyncCommands::hgetall(&mut conn, format!("task:{}", task_id)).await.unwrap();
    let _: () = redis::AsyncCommands::del(&mut conn, format!("task:{}", task_id)).await.unwrap();
    let _: () = redis::AsyncCommands::lrem(&mut conn, QUEUE_KEY, 0, &task_id).await.unwrap();
    (task_id, stored)
}

#[tokio::test]
async fn submit_then_status_round_trip() {
    let Some(url) = redis_url() else {
        eprintln!("REDIS_URL not set; skipping");
        return;
    };
    let state = test_state(&url);

    let body = multipart_body("file", Some("invoice.pdf"), PDF);
    let resp = app(state.clone()).oneshot(post_process(body, true)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);
    let submitted: serde_json::Value = serde_json::from_str(&body_string(resp).await).unwrap();
    assert_eq!(submitted["status"], "queued");
    let task_id = submitted["task_id"].as_str().unwrap().to_string();
    assert_eq!(task_id.len(), 36, "task_id should be a UUID");

    let resp = get(state.clone(), &format!("/status/{}", task_id)).await;
    assert_eq!(resp.status(), StatusCode::OK);
    let status: serde_json::Value = serde_json::from_str(&body_string(resp).await).unwrap();
    assert_eq!(status["task_id"], task_id);
    assert_eq!(status["status"], "queued");
    assert_eq!(status["attempts"], 0);
    assert!(status["result"].is_null());
    assert!(status["error"].is_null());
    assert!(status["warning"].is_null());

    let mut conn = state.redis_client.get_async_connection().await.unwrap();
    let stored: std::collections::HashMap<String, String> =
        redis::AsyncCommands::hgetall(&mut conn, format!("task:{}", task_id)).await.unwrap();
    assert_eq!(stored["status"], "queued");
    assert_eq!(stored["filename"], "invoice.pdf");
    assert_eq!(stored["extension"], "pdf");
    assert_eq!(stored["attempts"], "0");
    assert!(stored.contains_key("submitted_at"));
    let decoded = base64::Engine::decode(&base64::engine::general_purpose::STANDARD, &stored["data"]).unwrap();
    assert_eq!(decoded, PDF, "stored bytes must round-trip exactly");

    let queued: Vec<String> =
        redis::AsyncCommands::lrange(&mut conn, QUEUE_KEY, 0, -1).await.unwrap();
    assert!(queued.contains(&task_id));

    let _: () = redis::AsyncCommands::del(&mut conn, format!("task:{}", task_id)).await.unwrap();
    let _: () = redis::AsyncCommands::lrem(&mut conn, QUEUE_KEY, 0, &task_id).await.unwrap();
}

#[tokio::test]
async fn stored_extension_comes_from_content_not_filename() {
    let Some(url) = redis_url() else {
        eprintln!("REDIS_URL not set; skipping");
        return;
    };
    // A PDF uploaded under a misleading name must still be stored as a PDF, or
    // the SDK would hand it to the image loader and fail.
    let (_, stored) = submit_and_inspect(&url, "scan.jpg", PDF).await;
    assert_eq!(stored["extension"], "pdf");
    assert_eq!(stored["filename"], "scan.jpg", "original name is kept for the user");

    let (_, stored) = submit_and_inspect(&url, "photo.pdf", JPG).await;
    assert_eq!(stored["extension"], "jpg");

    let (_, stored) = submit_and_inspect(&url, "noext", PNG).await;
    assert_eq!(stored["extension"], "png");
}
