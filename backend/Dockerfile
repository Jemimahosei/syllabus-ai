# SyllabusAI — single-service Docker build.
# Stage 1 builds the React frontend; stage 2 compiles the C++ parser;
# the runtime stage serves the API + the built frontend from one service.
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS cpp
RUN apt-get update && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /cpp
COPY backend/parser_cpp/syllabus_parser.cpp ./
RUN g++ -std=c++17 -O2 -o syllabus_parser syllabus_parser.cpp

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
ENV SYLLABUS_PARSER_BIN=/app/syllabus_parser
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=cpp /cpp/syllabus_parser ./syllabus_parser
COPY --from=frontend /build/dist ./frontend_dist
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
