# 📊 FinSight: Personal Financial Intelligence

FinSight is a professional-grade personal finance analyzer that transforms messy bank statements and crumpled receipts into actionable behavioral insights. Powered by Gemini 1.5 Flash and a robust async processing pipeline, it gives you a "Chat GPT" for your own money.

![FinSight Dashboard](https://images.unsplash.com/photo-1554224155-6726b3ff858f?auto=format&fit=crop&q=80&w=1000)

## 🚀 Key Features

*   **⚡ Smart Ingestion**: Upload Google Pay or UPI PDF statements. The system automatically extracts merchants, amounts, and dates using intelligent pattern matching and LLM refinement.
*   **📸 Receipt OCR**: Upload images of paper receipts. A background worker (Celery + PaddleOCR) processes the image, extracts line items, and categorizes the spend.
*   **🤖 AI Finance Assistant**: Ask questions like *"How much did I spend on food in January?"* or *"Compare my weekend spending vs weekdays"*.
*   **🧠 Behavioral Insights**: Generates an "Executive Report" that identifies spending habits, impulse signals, and provides a "Financial Health Score."
*   **🔍 Merchant Resolution**: Automatically pulls canonical business names and categories (e.g., "ZOMATO" -> "Food & Dining").

## 🛠 Tech Stack

*   **Frontend**: React + Vite, Tailwind-inspired custom CSS, Lucide Icons.
*   **Backend**: FastAPI (Python 3.11).
*   **AI/ML**: Google Gemini 1.5 Flash, LayoutLMv3, PaddleOCR.
*   **Storage**: Local JSON Persistence & ChromaDB Vector Store.
*   **Async Processing**: Celery + Redis.
*   **DevOps**: Docker & Docker Compose.

---

## 🚦 Quick Start (Docker)

The easiest way to run FinSight is using Docker Compose.

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/asmitk991/FinSight.git
    cd FinSight
    ```

2.  **Set up Environment Variables**:
    Create a `.env` file in the root directory:
    ```bash
    GEMINI_API_KEY=your_google_gemini_api_key_here
    ```

3.  **Launch the App**:
    ```bash
    docker-compose up --build
    ```

4.  **Access the Dashboard**:
    *   **Frontend**: [http://localhost](http://localhost)
    *   **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📂 Project Structure

```text
├── backend/
│   ├── app/              # FastAPI Application Logic
│   ├── data/             # Persistent JSON & Ledger Data
│   ├── Dockerfile        # Backend Production Image
│   └── requirements.txt  # Python Dependencies
├── frontend/
│   ├── src/              # React Components & Dashboard
│   └── Dockerfile        # Nginx-based Frontend Image
└── docker-compose.yml    # Full-stack Orchestration
```

## 🔒 Privacy & Security

*   **Local-First**: All your transaction data is stored locally on your machine in the `backend/data` folder.
*   **Secure History**: This repository has been scrubbed of all personal test data and API keys.
*   **Ignored Files**: Sensitive files like `.env` and `transactions.json` are automatically ignored by Git.

---

## 📈 Future Roadmap

- [ ] Support for multi-user authentication (JWT).
- [ ] Direct bank API integrations (Plaid/Salt Edge).
- [ ] Export to PDF/Excel spending reports.
- [ ] Mobile-native application.

Made with ❤️ for better financial clarity.
