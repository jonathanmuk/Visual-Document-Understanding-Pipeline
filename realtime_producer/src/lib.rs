use axum::{
    extract::{DefaultBodyLimit, Multipart, Path, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use base64::{engine::general_purpose, Engine as _};
use redis::AsyncCommands;
use serde::Serialize;
use std::sync::Arc;
use tower_http::limit::RequestBodyLimitLayer;
use uuid::Uuid;

pub const MAX_UPLOAD_BYTES: usize = 10 * 1024 * 1024;
pub const QUEUE_KEY: &str = "ocr_tasks";

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
}

pub fn app(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/process", post(submit_task))
        .route("/status/:task_id", get(get_status))
        .route("/health", get(health))
        // Axum's default body limit is too small for real PDFs, so it is replaced
        // with an explicit ceiling. Keeping a ceiling protects the API from a
        // single oversized upload exhausting memory.
        .layer(DefaultBodyLimit::disable())
        .layer(RequestBodyLimitLayer::new(MAX_UPLOAD_BYTES))
        .with_state(state)
}

pub fn extension_from_filename(filename: &str) -> String {
    filename.split('.').last().unwrap_or("pdf").to_string()
}

async fn submit_task(
    State(state): State<Arc<AppState>>,
    mut multipart: Multipart,
) -> Result<impl IntoResponse, (StatusCode, String)> {
    let task_id = Uuid::new_v4().to_string();

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?
    {
        if field.name() == Some("file") {
            let filename = field.file_name().unwrap_or("unknown.pdf").to_string();
            let extension = extension_from_filename(&filename);

            let data = field
                .bytes()
                .await
                .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;
            let base64_data = general_purpose::STANDARD.encode(&data);

            // Redis is only contacted once there is something to store, so a bad
            // request is rejected without needing Redis at all.
            let mut conn = state
                .redis_client
                .get_async_connection()
                .await
                .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

            let task_key = format!("task:{}", task_id);

            // All fields are written in one HSET so the worker can never observe a
            // half-written task (for example a status of "queued" with no data yet).
            let _: () = redis::cmd("HSET")
                .arg(&task_key)
                .arg("status").arg("queued")
                .arg("filename").arg(&filename)
                .arg("extension").arg(&extension)
                .arg("data").arg(&base64_data)
                .query_async(&mut conn)
                .await
                .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

            // The worker consumes this list, and KEDA scales workers on its length.
            let _: () = conn
                .lpush(QUEUE_KEY, &task_id)
                .await
                .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

            return Ok((
                StatusCode::ACCEPTED,
                Json(TaskResponse {
                    task_id,
                    status: "queued".to_string(),
                }),
            ));
        }
    }

    Err((
        StatusCode::BAD_REQUEST,
        "Missing 'file' field in multipart form".to_string(),
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

    let exists: bool = conn
        .exists(&task_key)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    if !exists {
        return Err((StatusCode::NOT_FOUND, "Task ID not found".to_string()));
    }

    let data: std::collections::HashMap<String, String> = conn
        .hgetall(&task_key)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let status = data.get("status").cloned().unwrap_or_else(|| "unknown".to_string());
    let error = data.get("error").cloned();
    let result = data
        .get("result")
        .and_then(|r| serde_json::from_str(r).ok());

    Ok(Json(StatusResponse {
        task_id,
        status,
        result,
        error,
    }))
}

async fn health() -> impl IntoResponse {
    StatusCode::OK
}

#[cfg(test)]
mod tests {
    use super::extension_from_filename;

    #[test]
    fn takes_the_last_dotted_segment() {
        assert_eq!(extension_from_filename("invoice.pdf"), "pdf");
        assert_eq!(extension_from_filename("scan.final.PNG"), "PNG");
    }

    #[test]
    fn falls_back_to_the_whole_name_when_there_is_no_dot() {
        // Documents the current behaviour: a name with no dot becomes its own
        // extension. Gap 21 in Phase 2 replaces this with content sniffing.
        assert_eq!(extension_from_filename("nodot"), "nodot");
    }

    #[test]
    fn empty_name_yields_empty_extension() {
        assert_eq!(extension_from_filename(""), "");
    }
}
