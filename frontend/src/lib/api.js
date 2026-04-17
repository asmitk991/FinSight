import axios from "axios";
import { supabase } from "./supabase";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

const api = axios.create({
  baseURL: API_URL,
});

// Add a request interceptor to attach the JWT token
api.interceptors.request.use(async (config) => {
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.access_token) {
    config.headers.Authorization = `Bearer ${session.access_token}`;
  }
  return config;
});

export async function uploadPdf(file) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post("/ingest/pdf", formData);
  return data;
}

export async function confirmPdf(previewId, transactionIds) {
  const { data } = await api.post("/ingest/pdf/confirm", {
    preview_id: previewId,
    transaction_ids: transactionIds,
  });
  return data;
}

export async function uploadImages(files) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const { data } = await api.post("/ingest/image", formData);
  return data;
}

export async function pollImageJob(jobId) {
  const { data } = await api.get(`/ingest/image/jobs/${jobId}`);
  return data;
}

export async function fetchTransactions() {
  const { data } = await api.get("/transactions");
  return data;
}

export async function deleteTransaction(id) {
  const { data } = await api.delete(`/transactions/${id}`);
  return data;
}

export async function clearTransactions() {
  const { data } = await api.delete("/transactions");
  return data;
}

export async function askAgent(question) {
  const { data } = await api.post("/agent/query", { question });
  return data;
}

export async function fetchReport(start_date, end_date) {
  const { data } = await api.post("/agent/report", { start_date, end_date });
  return data;
}

export async function generateExecutiveReport() {
  const { data } = await api.post("/agent/executive-report", {});
  return data;
}
