use axum::{
    body::Body,
    extract::{DefaultBodyLimit, MatchedPath, Multipart, Path, State},
    http::{header, Request, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use base64::{engine::general_purpose, Engine as _};
use once_cell::sync::Lazy;
use prometheus::{Encoder, HistogramVec, IntCounterVec, TextEncoder};
use redis::AsyncCommands;
use serde::Serialize;
use std::sync::Arc;
use tower_http::limit::RequestBodyLimitLayer;
use uuid::Uuid;

pub const MAX_UPLOAD_BYTES: usize = 10 * 1024 * 1024;
pub const QUEUE_KEY: &str = "ocr_tasks";

static HTTP_REQUESTS: Lazy<IntCounterVec> = Lazy::new(|| {
    prometheus::register_int_counter_vec!(
        "vus_http_requests_total",
        "HTTP requests by route and status",
        &["route", "status"]
    )
    .unwrap()
});
static UPLOADS_REJECTED: Lazy<IntCounterVec> = Lazy::new(|| {
    prometheus::register_int_counter_vec!(
        "vus_uploads_rejected_total",
        "Uploads rejected before queueing, by reason",
        &["reason"]
    )
    .unwrap()
});
static UPLOAD_BYTES: Lazy<HistogramVec> = Lazy::new(|| {
    prometheus::register_histogram_vec!(
        "vus_upload_bytes",
        "Size of accepted uploads",
        &["type"],
        vec![10_000.0, 50_000.0, 100_000.0, 500_000.0, 1e6, 2e6, 5e6, 10e6]
    )
    .unwrap()
});

#[derive(Clone)]
pub struct AppState {
    pub redis_client: redis::Client,
}

#[derive(Serialize)]
pub struct TaskResponse {
    pub task_id: String,
    pub status: String,
}

#[derive(Serialize)]
pub struct StatusResponse {
    pub task_id: String,
    pub status: String,
    pub result: Option<serde_json::Value>,
    pub error: Option<String>,
    pub warning: Option<String>,
    pub attempts: Option<u32>,
}

pub fn redis_client_from_env() -> redis::Client {
    let host = std::env::var("REDIS_HOST").unwrap_or_else(|_| "ocr-redis-service".to_string());
    let port: u16 = std::env::var("REDIS_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(6379);
    let password = std::env::var("REDIS_PASSWORD").ok().filter(|p| !p.is_empty());
    redis::Client::open(redis::ConnectionInfo {
        addr: redis::ConnectionAddr::Tcp(host, port),
        redis: redis::RedisConnectionInfo {
            db: 0,
            username: None,
            password,
        },
    })
    .expect("Failed to create Redis client")
}

pub fn app(state: Arc<AppState>) -> Router {
    // Create the fixed label sets at zero now, so /metrics shows them from the
    // first scrape and a dashboard sees 0 rather than "no data".
    Lazy::force(&HTTP_REQUESTS);
    for reason in ["no_file", "empty", "unsupported_type"] {
        UPLOADS_REJECTED.with_label_values(&[reason]);
    }
    for kind in ["pdf", "png", "jpg"] {
        UPLOAD_BYTES.with_label_values(&[kind]);
    }

    Router::new()
        .route("/process", post(submit_task))
        .route("/status/:task_id", get(get_status))
        .route("/health", get(health))
        .route("/ready", get(ready))
        .route("/metrics", get(metrics))
        // Axum's default body limit is too small for real PDFs, so it is replaced
        // with an explicit ceiling. Keeping a ceiling protects the API from a
        // single oversized upload exhausting memory.
        .layer(DefaultBodyLimit::disable())
        .layer(RequestBodyLimitLayer::new(MAX_UPLOAD_BYTES))
        .layer(middleware::from_fn(count_requests))
        .with_state(state)
}

/// Identify a document by its first bytes. Only formats the SDK can read are
/// accepted; the stored extension comes from here, never from the filename.
pub fn detect_type(bytes: &[u8]) -> Option<&'static str> {
    if bytes.starts_with(b"%PDF-") {
        Some("pdf")
    } else if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        Some("png")
    } else if bytes.starts_with(&[0xFF, 0xD8, 0xFF]) {
        Some("jpg")
    } else {
        None
    }
}

async fn count_requests(req: Request<Body>, next: Next<Body>) -> Response {
    // The matched route pattern, not the raw path, so task IDs do not become
    // thousands of distinct metric labels.
    let route = req
        .extensions()
        .get::<MatchedPath>()
        .map(|p| p.as_str().to_string())
        .unwrap_or_else(|| "unmatched".to_string());
    let resp = next.run(req).await;
    HTTP_REQUESTS
        .with_label_values(&[&route, resp.status().as_str()])
        .inc();
    resp
}

fn reject(status: StatusCode, reason: &'static str, message: &str) -> (StatusCode, String) {
    UPLOADS_REJECTED.with_label_values(&[reason]).inc();
    (status, message.to_string())
}

async fn submit_task(
    State(state): State<Arc<AppState>>,
    mut multipart: Multipart,
) -> Result<impl IntoResponse, (StatusCode, String)> {
    // Size: RequestBodyLimitLayer already answers 413 when Content-Length is
    // over the limit, before this handler runs, and cuts off a stream that
    // declares no length. Those 413s appear in vus_http_requests_total.
    let task_id = Uuid::new_v4().to_string();

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?
    {
        if field.name() != Some("file") {
            continue;
        }

        let Some(filename) = field.file_name().map(|s| s.to_string()) else {
            return Err(reject(
                StatusCode::BAD_REQUEST,
                "no_file",
                "the 'file' field must be a file upload, not text (with curl, use file=@path)",
            ));
        };

        let data = field
            .bytes()
            .await
            .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;

        if data.is_empty() {
            return Err(reject(StatusCode::BAD_REQUEST, "empty", "the uploaded file is empty"));
        }

        let Some(extension) = detect_type(&data) else {
            return Err(reject(
                StatusCode::UNSUPPORTED_MEDIA_TYPE,
                "unsupported_type",
                "unsupported file type; send a PDF, PNG, or JPEG",
            ));
        };

        UPLOAD_BYTES
            .with_label_values(&[extension])
            .observe(data.len() as f64);
        let base64_data = general_purpose::STANDARD.encode(&data);

        // Redis is only contacted once there is something valid to store.
        let mut conn = state
            .redis_client
            .get_async_connection()
            .await
            .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

        let task_key = format!("task:{}", task_id);
        let submitted_at = format!("{:.3}", now_seconds());

        // All fields are written in one HSET so the worker can never observe a
        // half-written task (for example a status of "queued" with no data yet).
        let _: () = redis::cmd("HSET")
            .arg(&task_key)
            .arg("status").arg("queued")
            .arg("filename").arg(&filename)
            .arg("extension").arg(extension)
            .arg("attempts").arg(0)
            .arg("submitted_at").arg(&submitted_at)
            .arg("data").arg(&base64_data)
            .query_async(&mut conn)
            .await
            .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

        // The worker consumes this list, and KEDA scales workers on its length.
        let _: () = conn
            .lpush(QUEUE_KEY, &task_id)
            .await
            .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

        tracing::info!(task_id = %task_id, filename = %filename, detected = extension, bytes = data.len(), "task queued");

        return Ok((
            StatusCode::ACCEPTED,
            Json(TaskResponse {
                task_id,
                status: "queued".to_string(),
            }),
        ));
    }

    Err(reject(
        StatusCode::BAD_REQUEST,
        "no_file",
        "missing 'file' field in multipart form",
    ))
}

async fn get_status(
    State(state): State<Arc<AppState>>,
    Path(task_id): Path<String>,
) -> Result<impl IntoResponse, (StatusCode, String)> {
    let mut conn = state
        .redis_client
        .get_async_connection()
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let task_key = format!("task:{}", task_id);

    let data: std::collections::HashMap<String, String> = conn
        .hgetall(&task_key)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    if data.is_empty() {
        return Err((StatusCode::NOT_FOUND, "Task ID not found".to_string()));
    }

    let status = data.get("status").cloned().unwrap_or_else(|| "unknown".to_string());
    let error = data.get("error").cloned();
    let warning = data.get("warning").cloned();
    let attempts = data.get("attempts").and_then(|a| a.parse().ok());
    let result = data
        .get("result")
        .and_then(|r| serde_json::from_str(r).ok());

    Ok(Json(StatusResponse {
        task_id,
        status,
        result,
        error,
        warning,
        attempts,
    }))
}

async fn health() -> impl IntoResponse {
    StatusCode::OK
}

/// Readiness: the API can only do its job if Redis answers.
async fn ready(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    match state.redis_client.get_async_connection().await {
        Ok(mut conn) => match redis::cmd("PING").query_async::<_, String>(&mut conn).await {
            Ok(_) => (StatusCode::OK, "ready"),
            Err(_) => (StatusCode::SERVICE_UNAVAILABLE, "redis not answering"),
        },
        Err(_) => (StatusCode::SERVICE_UNAVAILABLE, "redis unreachable"),
    }
}

async fn metrics() -> impl IntoResponse {
    let mut buf = Vec::new();
    TextEncoder::new()
        .encode(&prometheus::gather(), &mut buf)
        .unwrap();
    (
        [(header::CONTENT_TYPE, "text/plain; version=0.0.4")],
        buf,
    )
}

fn now_seconds() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

#[cfg(test)]
mod tests {
    use super::detect_type;

    #[test]
    fn detects_the_three_supported_types() {
        assert_eq!(detect_type(b"%PDF-1.7 ..."), Some("pdf"));
        assert_eq!(detect_type(b"\x89PNG\r\n\x1a\n...."), Some("png"));
        assert_eq!(detect_type(&[0xFF, 0xD8, 0xFF, 0xE0, 0x00]), Some("jpg"));
    }

    #[test]
    fn rejects_everything_else() {
        assert_eq!(detect_type(b"hello world"), None);
        assert_eq!(detect_type(b"GIF89a"), None);
        assert_eq!(detect_type(b"RIFF....WEBP"), None);
        assert_eq!(detect_type(b""), None);
        assert_eq!(detect_type(b"%PD"), None, "truncated header is not a PDF");
    }
}
