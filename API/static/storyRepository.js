/**
 * STORY REPOSITORY (Model Layer - Data Access)
 * Responsible for raw API requests (AJAX calls) to the FastAPI server.
 */
class StoryRepository {
    constructor(apiBase = '/api/v1/ai') {
        this.apiBase = apiBase;
    }

    /**
     * Fetch list of active models.
     */
    async getModels() {
        const response = await fetch(`${this.apiBase}/models`);
        if (!response.ok) {
            throw new Error(`Failed to fetch models: ${response.statusText}`);
        }
        return await response.json();
    }

    /**
     * Trigger chapter generation (Async, returns 202 and Job ID).
     */
    async generateChapter(storyId, payload, headers = {}) {
        const response = await fetch(`${this.apiBase}/stories/${storyId}/chapters/generate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...headers
            },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Generation trigger failed: ${response.statusText}`);
        }
        return await response.json();
    }

    /**
     * Fetch the status of a generation job.
     */
    async getJobStatus(jobId) {
        const response = await fetch(`${this.apiBase}/jobs/${jobId}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch job status: ${response.statusText}`);
        }
        return await response.json();
    }

    /**
     * Approve a generated chapter version.
     */
    async approveChapter(storyId, chapterId, versionId, userId) {
        const response = await fetch(`${this.apiBase}/stories/${storyId}/chapters/${chapterId}/approve`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                version_id: versionId.toString(),
                approved_by: userId,
                update_memory: true
            })
        });
        if (!response.ok) {
            throw new Error(`Approve chapter failed: ${response.statusText}`);
        }
        return await response.json();
    }

    /**
     * Submit manual feedback or regenerate chapter.
     */
    async submitFeedback(storyId, chapterId, versionId, feedback, action, userId) {
        const response = await fetch(`${this.apiBase}/stories/${storyId}/chapters/${chapterId}/feedback`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-Id': userId
            },
            body: JSON.stringify({
                version_id: versionId.toString(),
                feedback: feedback,
                action: action
            })
        });
        if (!response.ok) {
            throw new Error(`Feedback submission failed: ${response.statusText}`);
        }
        return await response.json();
    }

    /**
     * Regenerate chapter version (using feedback).
     */
    async regenerateChapter(storyId, chapterId, baseVersionId, feedback, modelName, headers = {}) {
        const response = await fetch(`${this.apiBase}/stories/${storyId}/chapters/${chapterId}/regenerate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...headers
            },
            body: JSON.stringify({
                base_version_id: baseVersionId.toString(),
                feedback: feedback,
                model: modelName
            })
        });
        if (!response.ok) {
            throw new Error(`Regenerate failed: ${response.statusText}`);
        }
        return await response.json();
    }

    /**
     * Trigger chapter generation synchronously (Sync, returns 200 and complete results).
     */
    async generateChapterSync(storyId, payload, headers = {}) {
        const response = await fetch(`${this.apiBase}/stories/${storyId}/chapters/generate-sync`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...headers
            },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Sync generation failed: ${response.statusText}`);
        }
        return await response.json();
    }

    /**
     * Continue writing the chapter.
     */
    async continueChapter(storyId, chapterId, payload, headers = {}) {
        const response = await fetch(`${this.apiBase}/stories/${storyId}/chapters/${chapterId}/continue`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...headers
            },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Continue chapter failed: ${response.statusText}`);
        }
        return await response.json();
    }

    /**
     * Analyze a specific chapter version.
     */
    async analyzeChapter(storyId, chapterId, payload, headers = {}) {
        const response = await fetch(`${this.apiBase}/stories/${storyId}/chapters/${chapterId}/analyze`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...headers
            },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Analyze chapter failed: ${response.statusText}`);
        }
        return await response.json();
    }

    /**
     * Cancel an active generation job.
     */
    async cancelJob(jobId, headers = {}) {
        const response = await fetch(`${this.apiBase}/jobs/${jobId}/cancel`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...headers
            }
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Cancel job failed: ${response.statusText}`);
        }
        return await response.json();
    }
}
