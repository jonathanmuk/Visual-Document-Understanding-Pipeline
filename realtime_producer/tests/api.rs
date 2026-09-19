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

fn post_process(body: Vec<u8>) -> Request<Body> {
    Request::builder()
        .method("POST")
        .uri("/process")
        .header(
            header::CONTENT_TYPE,
            format!("multipart/form-data; boundary={}", BOUNDARY),
        )
        .body(Body::from(body))
        .unwrap()
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

// --- No Redis required ---------------------------------------------------------

#[tokio::test]
async fn health_returns_200() {
    let resp = app(no_redis_state())
        .oneshot(Request::get("/health").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
}

#[tokio::test]
async fn missing_file_field_is_rejected_without_touching_redis() {
    let body = multipart_body("not_file", Some("x.pdf"), b"%PDF-1.4");
    let resp = app(no_redis_state()).oneshot(post_process(body)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    assert!(body_string(resp).await.contains("Missing 'file' field"));
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
async fn upload_over_the_size_limit_is_rejected() {
    let oversized = vec![b'x'; MAX_UPLOAD_BYTES + 1024];
    let body = multipart_body("file", Some("big.pdf"), &oversized);
    let resp = app(no_redis_state()).oneshot(post_process(body)).await.unwrap();
    // The limit is enforced, which is what matters. But the multipart extractor
    // reports it as a generic 400 rather than 413 Payload Too Large, so a client
    // cannot tell "too big" from "malformed". Logged as gap 22 for Phase 2.
    assert_ne!(resp.status(), StatusCode::ACCEPTED, "oversized upload must not be accepted");
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn unknown_route_is_404() {
    let resp = app(no_redis_state())
        .oneshot(Request::get("/nope").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

// --- Redis required (skipped when REDIS_URL is unset) ------------------------

#[tokio::test]
async fn unknown_task_id_returns_404() {
    let Some(url) = redis_url() else {
        eprintln!("REDIS_URL not set; skipping");
        return;
    };
    let resp = app(test_state(&url))
        .oneshot(
            Request::get("/status/00000000-0000-0000-0000-000000000000")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn submit_then_status_round_trip() {
    let Some(url) = redis_url() else {
        eprintln!("REDIS_URL not set; skipping");
        return;
    };
    let state = test_state(&url);
    let content = b"%PDF-1.4\n%fake\n";

    // Submit.
    let body = multipart_body("file", Some("invoice.pdf"), content);
    let resp = app(state.clone()).oneshot(post_process(body)).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);
    let submitted: serde_json::Value =
        serde_json::from_str(&body_string(resp).await).unwrap();
    assert_eq!(submitted["status"], "queued");
    let task_id = submitted["task_id"].as_str().unwrap().to_string();
    assert_eq!(task_id.len(), 36, "task_id should be a UUID");

    // Status endpoint reflects it.
    let resp = app(state.clone())
        .oneshot(
            Request::get(format!("/status/{}", task_id))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let status: serde_json::Value = serde_json::from_str(&body_string(resp).await).unwrap();
    assert_eq!(status["task_id"], task_id);
    assert_eq!(status["status"], "queued");
    assert!(status["result"].is_null());
    assert!(status["error"].is_null());

    // What actually landed in Redis, which is what the worker will read.
    let mut conn = state.redis_client.get_async_connection().await.unwrap();
    let stored: std::collections::HashMap<String, String> = redis::AsyncCommands::hgetall(
        &mut conn,
        format!("task:{}", task_id),
    )
    .await
    .unwrap();
    assert_eq!(stored["status"], "queued");
    assert_eq!(stored["filename"], "invoice.pdf");
    assert_eq!(stored["extension"], "pdf");
    let decoded = base64::Engine::decode(&base64::engine::general_purpose::STANDARD, &stored["data"]).unwrap();
    assert_eq!(decoded, content, "stored bytes must round-trip exactly");

    // And it is on the queue the worker consumes.
    let queued: Vec<String> =
        redis::AsyncCommands::lrange(&mut conn, QUEUE_KEY, 0, -1).await.unwrap();
    assert!(queued.contains(&task_id));

    // Clean up so repeated runs do not accumulate.
    let _: () = redis::AsyncCommands::del(&mut conn, format!("task:{}", task_id)).await.unwrap();
    let _: () = redis::AsyncCommands::lrem(&mut conn, QUEUE_KEY, 0, &task_id).await.unwrap();
}
