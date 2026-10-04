use axum::{
    body::Body,
    extract::{DefaultBodyLimit, MatchedPath, Multipart, Path, State},
    http::{header, HeaderMap, Request, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use once_cell::sync::Lazy;
use prometheus::{Encoder, HistogramVec, IntCounterVec, TextEncoder};
use redis::{aio::ConnectionManager, AsyncCommands};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::sync::Arc;
use tokio::sync::OnceCell;
use tower_http::limit::RequestBodyLimitLayer;
use uuid::Uuid;

/// Largest document accepted. A file of exactly this size is allowed.
pub const MAX_FILE_BYTES: usize = 10 * 1024 * 1024;
/// The request body carries the file plus multipart framing, so the body limit
/// sits a little above the file limit. Without this allowance a file of exactly
/// MAX_FILE_BYTES would be refused.
pub const MAX_BODY_BYTES: usize = MAX_FILE_BYTES + 64 * 1024;
pub const QUEUE_KEY: &str = "ocr_tasks";
const MAX_CALLBACK_URL_LEN: usize = 2048;

static HTTP_REQUESTS: Lazy<IntCounterVec> = Lazy::new(|| {
    prometheus::register_int_counter_vec!(
        "vdu_http_requests_total",
        "HTTP requests by route and status",
        &["route", "status"]
    )
    .unwrap()
});
static UPLOADS_REJECTED: Lazy<IntCounterVec> = Lazy::new(|| {
    prometheus::register_int_counter_vec!(
        "vdu_uploads_rejected_total",
        "Uploads rejected before queueing, by reason",
        &["reason"]
    )
    .unwrap()
});
static UPLOAD_BYTES: Lazy<HistogramVec> = Lazy::new(|| {
    prometheus::register_histogram_vec!(
        "vdu_upload_bytes",
        "Size of accepted uploads",
        &["type"],
        vec![10_000.0, 50_000.0, 100_000.0, 500_000.0, 1e6, 2e6, 5e6, 10e6]
    )
    .unwrap()
});
static CACHE: Lazy<IntCounterVec> = Lazy::new(|| {
    prometheus::register_int_counter_vec!(
        "vdu_cache_total",
        "Result cache lookups by outcome",
        &["outcome"]
    )
    .unwrap()
});

#[derive(Clone, Debug)]
pub struct Config {
    /// How long an unfinished task and its document may live in Redis.
    pub task_max_age_seconds: u64,
    /// Return stored results for byte-identical documents.
    pub result_cache: bool,
    /// Part of the cache key. Bump it when prompts or region rules change, so
    /// results produced under the old rules are not served.
    pub pipeline_version: String,
    /// Also part of the cache key, so switching profile never serves results
    /// produced under another profile.
    pub profile: String,
    /// Hosts a callback_url may point at. Empty means callbacks are disabled.
    pub callback_allowed_hosts: Vec<String>,
    /// Permit plain http callbacks. For local testing only.
    pub callback_allow_http: bool,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            task_max_age_seconds: 172_800,
            result_cache: true,
            pipeline_version: "1".to_string(),
            profile: "default".to_string(),
            callback_allowed_hosts: vec![],
            callback_allow_http: false,
        }
    }
}

impl Config {
    pub fn from_env() -> Self {
        let d = Config::default();
        let flag = |name: &str, default: bool| {
            std::env::var(name)
                .map(|v| matches!(v.to_ascii_lowercase().as_str(), "1" | "true" | "on" | "yes"))
                .unwrap_or(default)
        };
        Config {
            task_max_age_seconds: std::env::var("TASK_MAX_AGE_SECONDS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(d.task_max_age_seconds),
            result_cache: flag("RESULT_CACHE", d.result_cache),
            pipeline_version: std::env::var("PIPELINE_VERSION").unwrap_or(d.pipeline_version),
            profile: std::env::var("VDU_PROFILE")
                .ok()
                .filter(|p| !p.is_empty())
                .unwrap_or(d.profile),
            callback_allowed_hosts: std::env::var("CALLBACK_ALLOWED_HOSTS")
                .unwrap_or_default()
                .split(',')
                .map(|h| h.trim().to_ascii_lowercase())
                .filter(|h| !h.is_empty())
                .collect(),
            callback_allow_http: flag("CALLBACK_ALLOW_HTTP", false),
        }
    }
}

pub struct AppState {
    pub redis_client: redis::Client,
    pub config: Config,
    // One multiplexed connection shared by every request, opened on first use
    // and reconnected automatically. Opening a connection per request capped
    // small-upload throughput at about 144 per second when measured.
    conn: OnceCell<ConnectionManager>,
}

impl AppState {
    pub fn new(redis_client: redis::Client, config: Config) -> Self {
        AppState { redis_client, config, conn: OnceCell::new() }
    }

    async fn redis(&self) -> Result<ConnectionManager, (StatusCode, String)> {
        self.conn
            .get_or_try_init(|| ConnectionManager::new(self.redis_client.clone()))
            .await
            .cloned()
            .map_err(|e| (StatusCode::SERVICE_UNAVAILABLE, format!("redis unavailable: {e}")))
    }
}

#[derive(Serialize)]
pub struct TaskResponse {
    pub task_id: String,
    pub status: String,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub cached: bool,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub deduplicated: bool,
}

#[derive(Serialize)]
pub struct StatusResponse {
    pub task_id: String,
    pub status: String,
    pub result: Option<serde_json::Value>,
    pub error: Option<String>,
    pub warning: Option<String>,
    pub attempts: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub callback_status: Option<String>,
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
    for reason in ["no_file", "empty", "too_large", "unsupported_type", "bad_callback"] {
        UPLOADS_REJECTED.with_label_values(&[reason]);
    }
    for kind in ["pdf", "png", "jpg"] {
        UPLOAD_BYTES.with_label_values(&[kind]);
    }
    for outcome in ["hit", "dedupe", "miss", "bypass"] {
        CACHE.with_label_values(&[outcome]);
    }

    Router::new()
        .route("/process", post(submit_task))
        .route("/status/:task_id", get(get_status))
        .route("/health", get(health))
        .route("/ready", get(ready))
        .route("/metrics", get(metrics))
        // Axum's default body limit is too small for real PDFs, so it is replaced
        // with an explicit ceiling that protects the API from an oversized upload.
        .layer(DefaultBodyLimit::disable())
        .layer(RequestBodyLimitLayer::new(MAX_BODY_BYTES))
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

/// Decide whether a callback URL is one this server may call. Callbacks are an
/// outbound request made on a client's say-so, so without a host allowlist they
/// would let any client make the cluster call any address it can reach,
/// including internal services (server-side request forgery).
pub fn validate_callback(raw: &str, config: &Config) -> Result<String, String> {
    if config.callback_allowed_hosts.is_empty() {
        return Err("callbacks are not enabled on this server".to_string());
    }
    if raw.len() > MAX_CALLBACK_URL_LEN {
        return Err(format!("callback_url is longer than {MAX_CALLBACK_URL_LEN} characters"));
    }
    let url = url::Url::parse(raw).map_err(|e| format!("callback_url is not a valid URL: {e}"))?;
    match url.scheme() {
        "https" => {}
        "http" if config.callback_allow_http => {}
        other => return Err(format!("callback_url must use https (got {other})")),
    }
    let host = url
        .host_str()
        .ok_or_else(|| "callback_url has no host".to_string())?
        .to_ascii_lowercase();
    let allowed = config.callback_allowed_hosts.iter().any(|pattern| {
        match pattern.strip_prefix("*.") {
            Some(suffix) => host.ends_with(&format!(".{suffix}")),
            None => &host == pattern,
        }
    });
    if !allowed {
        return Err(format!("callback host {host} is not in the allowed list"));
    }
    Ok(url.to_string())
}

pub fn cache_key(config: &Config, data: &[u8]) -> String {
    let digest = Sha256::digest(data);
    format!("cache:{}:{}:{:x}", config.pipeline_version, config.profile, digest)
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

fn internal(e: redis::RedisError) -> (StatusCode, String) {
    (StatusCode::INTERNAL_SERVER_ERROR, e.to_string())
}

fn wants_fresh(headers: &HeaderMap) -> bool {
    headers
        .get(header::CACHE_CONTROL)
        .and_then(|v| v.to_str().ok())
        .map(|v| v.to_ascii_lowercase().contains("no-cache"))
        .unwrap_or(false)
}

async fn submit_task(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    mut multipart: Multipart,
) -> Result<Response, (StatusCode, String)> {
    let mut file: Option<(String, axum::body::Bytes)> = None;
    let mut callback: Option<String> = None;

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?
    {
        match field.name() {
            Some("file") => {
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
                file = Some((filename, data));
            }
            Some("callback_url") => {
                let text = field
                    .text()
                    .await
                    .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;
                callback = Some(text.trim().to_string());
            }
            _ => {}
        }
    }

    let Some((filename, data)) = file else {
        return Err(reject(StatusCode::BAD_REQUEST, "no_file", "missing 'file' field in multipart form"));
    };
    if data.is_empty() {
        return Err(reject(StatusCode::BAD_REQUEST, "empty", "the uploaded file is empty"));
    }
    if data.len() > MAX_FILE_BYTES {
        return Err(reject(
            StatusCode::PAYLOAD_TOO_LARGE,
            "too_large",
            &format!("the file is {} bytes; the limit is {} bytes", data.len(), MAX_FILE_BYTES),
        ));
    }
    let Some(extension) = detect_type(&data) else {
        return Err(reject(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "unsupported_type",
            "unsupported file type; send a PDF, PNG, or JPEG",
        ));
    };
    let callback = match callback.filter(|c| !c.is_empty()) {
        Some(raw) => Some(
            validate_callback(&raw, &state.config)
                .map_err(|m| reject(StatusCode::BAD_REQUEST, "bad_callback", &m))?,
        ),
        None => None,
    };

    UPLOAD_BYTES.with_label_values(&[extension]).observe(data.len() as f64);
    let mut conn = state.redis().await?;
    let cfg = &state.config;

    // The result cache. A byte-identical document already done is answered at
    // once; one already waiting or in progress is joined rather than repeated.
    // A request with a callback always gets its own task, so its callback fires.
    let key = cfg.result_cache.then(|| cache_key(cfg, &data));
    if let Some(key) = &key {
        if wants_fresh(&headers) || callback.is_some() {
            CACHE.with_label_values(&["bypass"]).inc();
        } else if let Some(existing) = conn.get::<_, Option<String>>(key).await.map_err(internal)? {
            let status: Option<String> = conn
                .hget(format!("task:{existing}"), "status")
                .await
                .map_err(internal)?;
            match status.as_deref() {
                Some("done") => {
                    CACHE.with_label_values(&["hit"]).inc();
                    tracing::info!(task_id = %existing, filename = %filename, "served from cache");
                    let body = TaskResponse { task_id: existing, status: "done".into(), cached: true, deduplicated: false };
                    return Ok((StatusCode::OK, Json(body)).into_response());
                }
                Some(s @ ("queued" | "processing")) => {
                    CACHE.with_label_values(&["dedupe"]).inc();
                    let body = TaskResponse { task_id: existing, status: s.into(), cached: false, deduplicated: true };
                    return Ok((StatusCode::ACCEPTED, Json(body)).into_response());
                }
                _ => CACHE.with_label_values(&["miss"]).inc(),
            }
        } else {
            CACHE.with_label_values(&["miss"]).inc();
        }
    }

    let task_id = Uuid::new_v4().to_string();
    let task_key = format!("task:{task_id}");
    let data_key = format!("taskdata:{task_id}");
    let ttl = cfg.task_max_age_seconds;

    let mut fields: Vec<(&str, String)> = vec![
        ("status", "queued".into()),
        ("filename", filename.clone()),
        ("extension", extension.into()),
        ("attempts", "0".into()),
        ("submitted_at", format!("{:.3}", now_seconds())),
    ];
    if let Some(k) = &key {
        fields.push(("cache_key", k.clone()));
    }
    if let Some(cb) = &callback {
        fields.push(("callback_url", cb.clone()));
    }

    // One MULTI/EXEC: the document, the task, and its place in the queue appear
    // together or not at all, so a worker can never see a half-written task.
    // The document is stored as raw bytes in its own key: a third smaller than
    // base64, and a status check no longer drags it out of Redis.
    let mut pipe = redis::pipe();
    pipe.atomic()
        .cmd("SET").arg(&data_key).arg(&data[..]).arg("EX").arg(ttl).ignore()
        .hset_multiple(&task_key, &fields).ignore()
        .expire(&task_key, ttl as usize).ignore();
    if let Some(k) = &key {
        pipe.cmd("SET").arg(k).arg(&task_id).arg("EX").arg(ttl).ignore();
    }
    // The worker consumes this list, and KEDA scales workers on its length.
    pipe.lpush(QUEUE_KEY, &task_id).ignore();
    pipe.query_async::<_, ()>(&mut conn).await.map_err(internal)?;

    tracing::info!(task_id = %task_id, filename = %filename, detected = extension,
                   bytes = data.len(), callback = callback.is_some(), "task queued");

    let body = TaskResponse { task_id, status: "queued".into(), cached: false, deduplicated: false };
    Ok((StatusCode::ACCEPTED, Json(body)).into_response())
}

async fn get_status(
    State(state): State<Arc<AppState>>,
    Path(task_id): Path<String>,
) -> Result<impl IntoResponse, (StatusCode, String)> {
    let mut conn = state.redis().await?;
    let data: std::collections::HashMap<String, String> = conn
        .hgetall(format!("task:{task_id}"))
        .await
        .map_err(internal)?;
    if data.is_empty() {
        return Err((StatusCode::NOT_FOUND, "Task ID not found".to_string()));
    }

    Ok(Json(StatusResponse {
        task_id,
        status: data.get("status").cloned().unwrap_or_else(|| "unknown".to_string()),
        result: data.get("result").and_then(|r| serde_json::from_str(r).ok()),
        error: data.get("error").cloned(),
        warning: data.get("warning").cloned(),
        attempts: data.get("attempts").and_then(|a| a.parse().ok()),
        callback_status: data.get("callback_status").cloned(),
    }))
}

async fn health() -> impl IntoResponse {
    StatusCode::OK
}

/// Readiness: the API can only do its job if Redis answers.
async fn ready(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    match state.redis().await {
        Ok(mut conn) => match redis::cmd("PING").query_async::<_, String>(&mut conn).await {
            Ok(_) => (StatusCode::OK, "ready"),
            Err(_) => (StatusCode::SERVICE_UNAVAILABLE, "redis not answering"),
        },
        Err(_) => (StatusCode::SERVICE_UNAVAILABLE, "redis unreachable"),
    }
}

async fn metrics() -> impl IntoResponse {
    let mut buf = Vec::new();
    TextEncoder::new().encode(&prometheus::gather(), &mut buf).unwrap();
    ([(header::CONTENT_TYPE, "text/plain; version=0.0.4")], buf)
}

fn now_seconds() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;

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

    fn with_hosts(hosts: &[&str], allow_http: bool) -> Config {
        Config {
            callback_allowed_hosts: hosts.iter().map(|h| h.to_string()).collect(),
            callback_allow_http: allow_http,
            ..Config::default()
        }
    }

    #[test]
    fn callbacks_are_off_unless_hosts_are_listed() {
        let err = validate_callback("https://hooks.example.com/x", &Config::default()).unwrap_err();
        assert!(err.contains("not enabled"));
    }

    #[test]
    fn callback_host_must_be_listed() {
        let cfg = with_hosts(&["hooks.example.com", "*.corp.example"], false);
        assert!(validate_callback("https://hooks.example.com/x", &cfg).is_ok());
        assert!(validate_callback("https://a.b.corp.example/x", &cfg).is_ok());
        assert!(validate_callback("https://corp.example/x", &cfg).is_err(), "wildcard needs a subdomain");
        assert!(validate_callback("https://evil.example.com/x", &cfg).is_err());
        assert!(validate_callback("https://hooks.example.com.evil.net/x", &cfg).is_err());
        assert!(validate_callback("https://ocr-redis-service:6379/", &cfg).is_err(), "internal services refused");
    }

    #[test]
    fn callback_must_be_https_unless_http_is_allowed() {
        let strict = with_hosts(&["127.0.0.1"], false);
        assert!(validate_callback("http://127.0.0.1:9999/hook", &strict).unwrap_err().contains("https"));
        let local = with_hosts(&["127.0.0.1"], true);
        assert!(validate_callback("http://127.0.0.1:9999/hook", &local).is_ok());
        assert!(validate_callback("ftp://127.0.0.1/x", &local).is_err());
        assert!(validate_callback("not a url", &local).is_err());
    }

    #[test]
    fn cache_key_depends_on_content_version_and_profile() {
        let a = cache_key(&Config::default(), b"%PDF-1 one");
        assert_eq!(a, cache_key(&Config::default(), b"%PDF-1 one"), "same bytes, same key");
        assert_ne!(a, cache_key(&Config::default(), b"%PDF-1 two"));
        let v2 = Config { pipeline_version: "2".into(), ..Config::default() };
        assert_ne!(a, cache_key(&v2, b"%PDF-1 one"), "a new pipeline version must not reuse old results");
        let fin = Config { profile: "finance".into(), ..Config::default() };
        assert_ne!(a, cache_key(&fin, b"%PDF-1 one"), "a different profile must not reuse results");
    }
}
