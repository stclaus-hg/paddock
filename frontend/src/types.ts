export type QuestionType = 'bio' | 'stats' | 'mixed' | 'out_of_scope'

export interface Source {
  title: string
  url: string
}

export interface AskResponse {
  answer: string
  question_type: QuestionType | null
  sources: Source[]
  sql: string | null
}
