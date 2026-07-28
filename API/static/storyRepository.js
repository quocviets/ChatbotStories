/**
 * STORY REPOSITORY (Model Layer - Data Access)
 * Responsible for raw API requests (AJAX calls) to the FastAPI server.
 */
class StoryRepository {
    constructor(apiBase = '/api/v1/ai') {
        this.apiBase = apiBase;
    }

    async #request(path, errorMessage, options, readErrorDetail = false) {
        const response = await fetch(`${this.apiBase}${path}`, options);
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
            { title: thread.title, messages: thread.messages },
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

    async exportChatChapter(storyId, payload) {
        return this.#write(
            `/stories/${storyId}/chapters/from-chat`,
            'Export chat chapter failed',
            'POST',
            payload,
            {
                'Idempotency-Key': `chat_${payload.thread_id}_${payload.message_index}`,
                'X-Tenant-Id': 'tenant_web_01',
                'X-User-Id': 'user_web_01'
            },
            true
        );
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
