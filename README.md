# Binance Futures Bot (Template)
- 15m 메인 + 1h 추세필터
- EMA20/50 돌파 + RSI 강도 + 금일 고/저 돌파
- 레버리지 5x, 일 손실 한도 -3%
- 기본은 페이퍼 모드(live=false), 실거래 전환 시 config/config.yaml 수정

## 빠른 시작
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env
PYTHONPATH=src python -m src.runner

## Docker
docker build -t trading-bot .
docker run -d --name bot --env-file .env trading-bot
