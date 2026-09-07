/**
 * STORY REPOSITORY (Model Layer - Data Access)
 * Responsible for raw API requests (AJAX calls) to the FastAPI server.
 */
class StoryRepository {
    constructor(apiBase = '/api/v1/ai') {
        this.apiBase = apiBase;
    }

    #identityHeaders() {
        return {
            'X-Tenant-Id': 'tenant_web_01',
            'X-User-Id': 'user_web_01'
        };
    }

    async #request(path, errorMessage, options = {}, readErrorDetail = false) {
        const fetchOptions = { credentials: 'same-origin', ...options };
        const response = await fetch(`${this.apiBase}${path}`, fetchOptions);
        if (!response.ok) {
            let detail;
            if (readErrorDetail) {
                detail = (await response.json().catch(() => ({}))).detail;
                if (Array.isArray(detail)) {
                    detail = detail.map(error => `${error.loc?.at(-1) || 'request'}: ${error.msg || JSON.stringify(error)}`).join('; ');
                } else if (detail && typeof detail === 'object') {
                    detail = detail.message || JSON.stringify(detail);
                }
            }
            throw new Error(detail || `${errorMessage}: ${response.statusText}`);
        }
        return response.json();
    }

    #write(path, errorMessage, method, body, headers = {}, readErrorDetail = false) {
        const options = {
            method,
            headers: { 'Content-Type': 'application/json', ...headers }
        };
        if (body !== undefined) options.body = JSON.stringify(body);
        return this.#request(path, errorMessage, options, readErrorDetail);
    }

    /**
     * Fetch list of active models.
     */
    async getModels() {
        return this.#request('/models', 'Failed to fetch models');
    }

    async transcribe(blob) {
        return this.#request('/transcriptions', 'Chuyển giọng nói thất bại', {
            method: 'POST',
            headers: { 'Content-Type': blob.type },
            body: blob
        }, true);
    }

    async getStories() {
        return this.#request('/stories', 'Load stories failed', {
            headers: this.#identityHeaders()
        }, true);
    }

    async createStory(payload) {
        return this.#write(
            '/stories',
            'Create story failed',
            'POST',
            payload,
            this.#identityHeaders(),
            true
        );
    }

    async importLegacyStories(stories) {
        return this.#write(
            '/stories/import',
            'Import legacy stories failed',
            'POST',
            { stories },
            this.#identityHeaders(),
            true
        );
    }

    async updateStory(storyId, payload) {
        return this.#write(
            `/stories/${storyId}`,
            'Update story failed',
            'PATCH',
            payload,
            this.#identityHeaders(),
            true
        );
    }

    async searchLore(storyId, query, limit = 8) {
        const params = new URLSearchParams({ query, limit });
        return this.#request(`/stories/${storyId}/lore/search?${params}`, 'Lore search failed', undefined, true);
    }

    async chat(storyId, payload) {
        return this.#write(`/stories/${storyId}/chat`, 'Story chat failed', 'POST', payload, {}, true);
    }

    async getChatThreads(storyId) {
        return this.#request(`/stories/${storyId}/chats`, 'Load chats failed', undefined, true);
    }

    async saveChatThread(storyId, thread) {
        return this.#write(
            `/stories/${storyId}/chats/${thread.id}`,
            'Save chat failed',
            'PUT',
            {
                title: thread.title,
                messages: thread.messages.map(({ role, content }) => ({ role, content }))
            },
            {},
            true
        );
    }

    async deleteChatThread(storyId, threadId) {
        return this.#request(`/stories/${storyId}/chats/${threadId}`, 'Delete chat failed', {
            method: 'DELETE'
        }, true);
    }

    async deleteChapter(storyId, chapterId) {
        return this.#request(`/stories/${storyId}/chapters/${chapterId}`, 'Delete chapter failed', {
            method: 'DELETE'
        }, true);
    }

    async getChapters(storyId) {
        return this.#request(`/stories/${storyId}/chapters`, 'Load chapters failed', undefined, true);
    }

    async renameChapter(storyId, chapterId, title) {
        return this.#write(
            `/stories/${storyId}/chapters/${chapterId}`,
            'Rename chapter failed',
            'PATCH',
            { title },
            {},
            true
        );
    }

    async getChapter(storyId, chapterId) {
        return this.#request(`/stories/${storyId}/chapters/${chapterId}`, 'Load chapter failed', undefined, true);
    }

    /**
     * Trigger chapter generation (Async, returns 202 and Job ID).
     */
    async generateChapter(storyId, payload, headers = {}) {
        return this.#write(
            `/stories/${storyId}/chapters/generate`,
            'Generation trigger failed',
            'POST',
            payload,
            headers,
            true
        );
    }

    /**
     * Fetch the status of a generation job.
     */
    async getJobStatus(jobId) {
        return this.#request(`/jobs/${jobId}`, 'Failed to fetch job status');
    }

    /**
     * Approve a generated chapter version.
     */
    async approveChapter(storyId, chapterId, versionId, userId) {
        return this.#write(
            `/stories/${storyId}/chapters/${chapterId}/approve`,
            'Approve chapter failed',
            'POST',
            {
                version_id: versionId.toString(),
                approved_by: userId,
                update_memory: true
            }
        );
    }

    /**
     * Regenerate chapter version (using feedback).
     */
    async regenerateChapter(storyId, chapterId, baseVersionId, feedback, modelName, headers = {}) {
        return this.#write(
            `/stories/${storyId}/chapters/${chapterId}/regenerate`,
            'Regenerate failed',
            'POST',
            {
                base_version_id: baseVersionId.toString(),
                feedback,
                model: modelName
            },
            headers
        );
    }

    /**
     * Continue writing the chapter.
     */
    async continueChapter(storyId, chapterId, payload, headers = {}) {
        return this.#write(
            `/stories/${storyId}/chapters/${chapterId}/continue`,
            'Continue chapter failed',
            'POST',
            payload,
            headers,
            true
        );
    }

    /**
     * Analyze a specific chapter version.
     */
    async analyzeChapter(storyId, chapterId, payload, headers = {}) {
        return this.#write(
            `/stories/${storyId}/chapters/${chapterId}/analyze`,
            'Analyze chapter failed',
            'POST',
            payload,
            headers,
            true
        );
    }

    /**
     * Cancel an active generation job.
     */
    async cancelJob(jobId, headers = {}) {
        return this.#write(`/jobs/${jobId}/cancel`, 'Cancel job failed', 'POST', undefined, headers, true);
    }

    /**
     * Update chapter version content with user edits.
     */
    async updateChapterVersionContent(storyId, chapterId, versionId, content, headers = {}) {
        return this.#write(
            `/stories/${storyId}/chapters/${chapterId}/versions/${versionId}`,
            'Update version content failed',
            'PUT',
            { content },
            headers,
            true
        );
    }
}
