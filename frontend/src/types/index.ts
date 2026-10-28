export interface User {
  id: string;
  name: string;
  email: string;
  created_at: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Chat {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatListResponse {
  chats: Chat[];
}

export interface Citation {
  source: string;
  page: number;
}

export interface Message {
  id: string;
  chat_id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[] | null;
  created_at: string;
}

export interface MessageListResponse {
  messages: Message[];
}

/**
 * Per-page record from the layered PDF pipeline. Only "notable" pages are
 * persisted (OCR'd, still needing OCR, or carrying a warning), so the array
 * stays small even for a 1400-page book.
 */
export interface PageAudit {
  page: number;
  kind: 'digital' | 'scanned' | 'hybrid' | 'blank';
  chars: number;
  image_coverage: number;
  quality: number;
  needs_ocr: boolean;
  ocr_used: boolean;
  ocr_attempts: number;
  ocr_confidence: number | null;
  preprocess: string;
  text_source: string;
  out_chars: number;
  note?: string;
}

export interface ParseAudit {
  filename: string;
  total_pages: number;
  digital_pages: number;
  scanned_pages: number;
  hybrid_pages: number;
  blank_pages: number;
  ocr_pages: number;
  ocr_failed_pages: number;
  ocr_skipped_pages: number;
  ocr_truncated: boolean;
  ocr_engine: string | null;
  ocr_available: boolean;
  mean_confidence: number | null;
  low_confidence_pages: number[];
  text_chars: number;
  duration_seconds: number;
  warnings: string[];
  pages: PageAudit[];
}

export interface Document {
  id: string;
  chat_id: string;
  filename: string;
  file_type: string;
  upload_time: string;
  total_pages?: number | null;
  total_chunks?: number | null;
  status: 'processing' | 'processed' | 'failed';
  progress?: number | null;
  progress_stage?: string | null;
  parse_audit?: ParseAudit | null;
  error_message?: string | null;
}

export interface DocumentListResponse {
  documents: Document[];
}

export interface MCQOption {
  id: string;
  text: string;
}

export interface MCQQuestion {
  id: string;
  question: string;
  options: MCQOption[];
  correct_option_id: string;
  explanation: string;
}

export interface Quiz {
  id: string;
  chat_id: string;
  topic: string;
  score?: number | null;
  total_questions: number;
  weak_topics?: string[] | null;
  questions: MCQQuestion[];
  created_at: string;
}

export interface WrongQuestionDetail {
  question_id: string;
  question: string;
  user_answer: string;
  correct_answer: string;
  explanation: string;
}

export interface QuizResult {
  quiz_id: string;
  score: number;
  total_questions: number;
  correct_count: number;
  weak_topics: string[];
  feedback: string;
  wrong_questions?: WrongQuestionDetail[];
}

export interface RecommendationResponse {
  chat_id: string;
  recommendations: string;
  generated_at: string;
}

export * from './notes'
