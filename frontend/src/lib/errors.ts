/** Ошибка API в формате контракта: {error:{code,message,field?}}. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly field?: string

  constructor(status: number, code: string, message: string, field?: string) {
    super(message)
    this.status = status
    this.code = code
    this.field = field
  }

  /** Чужой или несуществующий объект. Контракт: 404, не 403. */
  get isNotFound() {
    return this.status === 404
  }

  get isUnauthorized() {
    return this.status === 401
  }
}
