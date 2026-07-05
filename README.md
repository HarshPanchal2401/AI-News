# AI Pulse

AI Pulse is a Personalized AI News Intelligence Platform that automatically curates, analyzes, and personalizes the latest news in the Artificial Intelligence space.

It is built with a **FastAPI** backend and features a modern, mobile-responsive **HTML/JS** frontend.

## 📁 Project Structure

- `backend/`: Contains the complete FastAPI application, database models, background scheduling tasks, Gemini AI integrations, and the frontend views (`backend/app/templates/index.html`).

## 🚀 Getting Started

To get the project up and running locally, please refer to the detailed **[Backend README](./backend/README.md)**. It contains step-by-step instructions on setting up your environment variables, installing dependencies, and running the server.

## ✨ Key Features

- **Automated Fetching**: Pulls AI news from 20 trusted sources daily.
- **AI-Powered Analysis**: Uses Gemini 2.5 Flash to generate summaries, identify mentioned companies, and score article importance.
- **Deduplication Engine**: Prevents identical news from cluttering your feed using semantic similarity.
- **Personalization**: Delivers a daily brief strictly tailored to your favorite companies, categories, and topics.
- **Responsive Web App**: Provides a sleek, interactive frontend designed for mobile and desktop screens.
