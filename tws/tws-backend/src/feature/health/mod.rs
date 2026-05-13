use crate::state::AppState;
use axum::routing::get;
use axum::{Json, Router};
use serde::Serialize;

#[derive(Serialize)]
struct HealthResponse {
    status: String,
}

async fn get_health() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".to_string(),
    })
}

pub fn create_router() -> Router<AppState> {
    Router::new().route("/", get(get_health))
}
