const API_ROOT = "/api/v1";
let csrfCapability = null;

export class ApiError extends Error {
  constructor(status, code, details = {}) {
    super(code || "request_failed");
    this.name = "ApiError";
    this.status = status;
    this.code = code || "request_failed";
    this.unresolvedPackageIds = Array.isArray(details.unresolvedPackageIds)
      ? details.unresolvedPackageIds.filter((value) => Number.isInteger(value) && value > 0).slice(0, 50)
      : [];
  }
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(options.method || "GET") && csrfCapability) {
    headers.set("X-Postify-CSRF", csrfCapability);
  }
  const response = await fetch(`${API_ROOT}${path}`, {...options, headers});
  if (!response.ok) {
    let code = "request_failed";
    let details = {};
    try {
      details = await response.json();
      code = details.code || code;
    } catch (_) { /* safe generic error */ }
    throw new ApiError(response.status, code, details);
  }
  return response.status === 204 ? null : response.json();
}

const projectPath = (projectId, resource) => `/projects/${projectId}/${resource}`;

export const getBootstrap = async (signal) => {
  const bootstrap = await request("/bootstrap", {signal});
  csrfCapability = bootstrap.csrfToken;
  return bootstrap;
};
export const getDashboard = (projectId, signal) => request(projectPath(projectId, "dashboard"), {signal});
export const getMaterials = (projectId, signal, status = null) => {
  const query = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : "";
  return request(`${projectPath(projectId, "materials")}${query}`, {signal});
};
export const getPackages = (projectId, signal) => request(projectPath(projectId, "packages"), {signal});
export const getPackage = (projectId, packageId, signal) => request(projectPath(projectId, `packages/${packageId}`), {signal});
export const getQueue = (projectId, signal) => request(projectPath(projectId, "queue"), {signal});
export const getPublications = (projectId, signal) => request(projectPath(projectId, "publications"), {signal});
export const getOperations = (projectId, signal) => request(projectPath(projectId, "operations"), {signal});
export const getOperation = (projectId, operationRunId, signal) => request(projectPath(projectId, `operations/${operationRunId}`), {signal});
export const getSettings = (projectId, signal) => request(projectPath(projectId, "settings"), {signal});
export const updateSettings = (projectId, section, payload) => request(projectPath(projectId, `settings/${section}`), {method: "PUT", body: JSON.stringify(payload)});
export const createResource = (projectId, resource, payload) => request(projectPath(projectId, resource), {method: "POST", body: JSON.stringify(payload)});
export const updateResource = (projectId, resource, resourceId, payload) => request(projectPath(projectId, `${resource}/${resourceId}`), {method: "PUT", body: JSON.stringify(payload)});
export const deleteResource = (projectId, resource, resourceId) => request(projectPath(projectId, `${resource}/${resourceId}`), {method: "DELETE"});
export const checkChannel = (projectId, channelId) => request(projectPath(projectId, `channels/${channelId}/check`), {method: "POST"});
export const removeChannelSecret = (projectId, channelId) => request(projectPath(projectId, `channels/${channelId}/secret/remove`), {method: "POST"});
export const approvePackage = (projectId, packageId) => request(`${projectPath(projectId, `packages/${packageId}`)}/approve`, {method: "POST"});
export const rejectPackage = (projectId, packageId) => request(`${projectPath(projectId, `packages/${packageId}`)}/reject`, {method: "POST"});
export const loadMorePackages = (projectId) => request(`${projectPath(projectId, "packages")}/load-more`, {method: "POST"});
export const retryAnalysis = (projectId, attemptId) => request(projectPath(projectId, `attempts/${attemptId}/retry-analysis`), {method: "POST"});
export const returnToAnalysis = (projectId, packageId) => request(`${projectPath(projectId, `packages/${packageId}`)}/return-to-analysis`, {method: "POST"});
export const regeneratePost = (projectId, packageId) => request(`${projectPath(projectId, `packages/${packageId}`)}/regenerate`, {method: "POST"});
export const replacePackageMedia = (projectId, packageId) => request(`${projectPath(projectId, `packages/${packageId}`)}/media/replace`, {method: "POST"});
export const publishNow = (projectId, packageId) => request(`${projectPath(projectId, `packages/${packageId}`)}/publish-now`, {method: "POST"});
export const retryDelivery = (projectId, deliveryId) => request(projectPath(projectId, `deliveries/${deliveryId}/retry`), {method: "POST"});
export const runOnce = (projectId) => request(projectPath(projectId, "operations/run-once"), {method: "POST"});
export const manualSearch = (projectId) => request(projectPath(projectId, "operations/search"), {method: "POST"});
export const publishOnce = (projectId) => request(projectPath(projectId, "operations/publish-once"), {method: "POST"});
