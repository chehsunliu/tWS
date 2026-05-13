use std::error::Error;

#[derive(Clone, Default)]
pub struct AppState {}

impl AppState {
    pub async fn from_env() -> Result<Self, Box<dyn Error>> {
        Ok(Self::default())
    }
}
