/**
 * STORY SERVICE (Model Layer - Business Logic)
 * Encapsulates workflows, state transitions, and SSE token streaming.
 */
class StoryService {
    constructor(repository) {
        this.repository = repository;
        this.currentJobId = null;
        this.eventSource = null;
        this.pollingJobId = null;
    }

    /**
     * Get list of models for selection dropdown.
     */
    async loadModels() {
        const result = await this.repository.getModels();
        return result.data || [];
    }

    #mapStory(story) {
        return {
            id: story.id,
            title: story.title,
            masterTone: story.master_tone || '',
            masterOutline: story.master_outline || '',
            createdAt: story.created_at,
            archivedAt: story.archived_at,
            chapterCount: Number(story.chapter_count || 0),
            chatCount: Number(story.chat_count || 0)
        };
    }

    async loadStories() {
        const result = await this.repository.getStories();
        return (result.data || []).map(story => this.#mapStory(story));
    }

    async importLegacyStories(stories) {
        if (!stories.length) return;
        await this.repository.importLegacyStories(stories.map(story => ({
            id: story.id,
            title: story.title,
            master_tone: story.masterTone || '',
            master_outline: story.masterOutline || '',
            created_at: story.createdAt || null,
            archived_at: story.archivedAt || null
        })));
    }

    async createStory(title, masterTone = '', masterOutline = '') {
        const result = await this.repository.createStory({
            title,
            master_tone: masterTone,
            master_outline: masterOutline
        });
        return this.#mapStory(result.data);
    }

    async setStoryArchived(storyId, archived) {
        const result = await this.repository.updateStory(storyId, { archived });
        return this.#mapStory(result.data);
    }

    async searchLore(storyId, query) {
        const result = await this.repository.searchLore(storyId, query);
        return result.data || [];
    }

    async chat(storyId, payload) {
        const result = await this.repository.chat(storyId, payload);
        return result.data.reply;
    }

    async loadChats(storyId) {
        const result = await this.repository.getChatThreads(storyId);
        return (result.data || []).map(thread => ({
            id: thread.id,
            title: thread.title,
            createdAt: thread.created_at,
            messages: thread.messages || []
        }));
    }

    async saveChatThread(storyId, thread) {
        return this.repository.saveChatThread(storyId, thread);
    }

    async deleteChatThread(storyId, threadId) {
        return this.repository.deleteChatThread(storyId, threadId);
    }

    async deleteChapter(storyId, chapterId) {
        return this.repository.deleteChapter(storyId, chapterId);
    }

    async loadChapters(storyId) {
        const result = await this.repository.getChapters(storyId);
        return {
            chapters: (result.data || []).map(chapter => ({
                chapterId: chapter.chapter_id,
                chapterNumber: chapter.chapter_number,
                versionId: chapter.version_id,
                title: chapter.title,
                content: chapter.content,
                model: chapter.model,
                status: chapter.status,
                sourceThreadId: chapter.thread_id,
                sourceMessageIndex: chapter.message_index
            })),
            deletedSources: (result.deleted_sources || []).map(source => ({
                chapterId: source.chapter_id,
                sourceThreadId: source.thread_id,
                sourceMessageIndex: source.message_index
            }))
        };
    }

    async renameChapter(storyId, chapterId, title) {
        return this.repository.renameChapter(storyId, chapterId, title);
    }

    async getChapter(storyId, chapterId) {
        const result = await this.repository.getChapter(storyId, chapterId);
        const chapter = result.data;
        return {
            chapterId: chapter.chapter_id,
            versionId: chapter.version_id,
            content: chapter.content,
            model: chapter.model,
            status: chapter.status,
            sourceThreadId: chapter.thread_id,
            sourceMessageIndex: chapter.message_index
        };
    }

    #generationRequest(formValues) {
        return {
            headers: {
                'Idempotency-Key': 'idemp_' + Date.now(),
                'X-Tenant-Id': 'tenant_web_01',
                'X-User-Id': 'user_web_01'
            },
            payload: {
                request: formValues.request,
                model: formValues.model,
                mode: 'ASYNC',
                chapter: {
                    title: formValues.title,
                    target_word_count: parseInt(formValues.wordCount),
                    tone: formValues.tone,
                    chapter_tone_override: formValues.chapterToneOverride,
                    master_tone: formValues.masterTone,
                    master_outline: formValues.masterOutline,
                    condensed_outline: formValues.condensedOutline,
                    character_wiki: formValues.characterWiki
                },
                generation_config: {
                    temperature: 0.8,
                    max_output_tokens: 3000,
                    max_revision_attempts: 2,
                    auto_analyze: true
                },
                constraints: formValues.constraints,
                metadata: formValues.metadata || {}
            }
        };
    }

    /**
     * Start the chapter generation process.
     */
    async startGeneration(storyId, formValues, onStatusChange, onTokenReceived, onComplete, onError) {
        try {
            const { headers, payload } = this.#generationRequest(formValues);

            // 1. Submit job
            const response = await this.repository.generateChapter(storyId, payload, headers);
            const jobId = response.data.job_id;
            this.currentJobId = jobId;

            onStatusChange({ status: 'QUEUED', progress: 5, step: 'QUEUED' });

            // 2. Connect to SSE Stream
            this.connectStream(jobId, onStatusChange, onTokenReceived, onComplete, onError);

        } catch (error) {
            console.error("Service error starting generation:", error);
            onError(error);
        }
    }

    /**
     * Connect to the Server-Sent Events stream for the job.
     */
    connectStream(jobId, onStatusChange, onTokenReceived, onComplete, onError) {
        if (this.eventSource) {
            this.eventSource.close();
        }

        const url = `/api/v1/ai/jobs/${jobId}/stream`;
        this.eventSource = new EventSource(url);
        console.log(`Connecting EventSource to: ${url}`);

        this.eventSource.addEventListener('status', (e) => {
            const data = JSON.parse(e.data);
            onStatusChange({
                status: data.status,
                progress: data.progress,
                step: data.current_step || data.status
            });
        });

        this.eventSource.addEventListener('token', (e) => {
            const data = JSON.parse(e.data);
            onTokenReceived(data.content);
        });

        this.eventSource.addEventListener('analysis', (e) => {
            const data = JSON.parse(e.data);
            onStatusChange({ analysis: data });
        });

        this.eventSource.addEventListener('completed', (e) => {
            const data = JSON.parse(e.data);
            this.eventSource.close();
            onComplete(data);
        });

        this.eventSource.onerror = (err) => {
            console.error("EventSource encountered an error:", err);
            this.eventSource.close();
            if (this.pollingJobId === jobId) return;
            this.pollingJobId = jobId;
            this.pollJobCompletion(jobId, onComplete, onError);
        };
    }

    /**
     * Fallback poll in case EventSource is closed or errored out early.
     */
    async pollJobCompletion(jobId, onComplete, onError) {
        let attempts = 0;
        const maxAttempts = 90;
        const interval = 2000;

        const check = async () => {
            try {
                const res = await this.repository.getJobStatus(jobId);
                const job = res.data;
                
                if (job.status === 'COMPLETED' || job.status === 'NEEDS_MANUAL_REVIEW') {
                    if (this.eventSource) this.eventSource.close();
                    this.pollingJobId = null;
                    onComplete(job.result);
                } else if (job.status === 'FAILED') {
                    if (this.eventSource) this.eventSource.close();
                    this.pollingJobId = null;
                    onError(new Error(job.error?.message || "Job failed."));
                } else if (job.status === 'CANCELLED') {
                    this.pollingJobId = null;
                    onError(new Error("Job was cancelled."));
                } else if (attempts < maxAttempts) {
                    attempts++;
                    setTimeout(check, interval);
                } else {
                    this.pollingJobId = null;
                    onError(new Error("Polling timeout waiting for completion."));
                }
            } catch (err) {
                this.pollingJobId = null;
                onError(err);
            }
        };

        setTimeout(check, interval);
    }

    /**
     * Approve the chapter version.
     */
    async approveChapter(storyId, chapterId, versionId) {
        return this.repository.approveChapter(storyId, chapterId, versionId, 'user_web_01');
    }

    /**
     * Reject and submit feedback (Regenerate).
     */
    async regenerateChapter(storyId, chapterId, baseVersionId, feedback, modelName) {
        const headers = {
            'Idempotency-Key': 'idemp_regen_' + Date.now(),
            'X-Tenant-Id': 'tenant_web_01',
            'X-User-Id': 'user_web_01'
        };
        const response = await this.repository.regenerateChapter(storyId, chapterId, baseVersionId, feedback, modelName, headers);
        return response.data;
    }

    /**
     * Continue writing the chapter.
     */
    async continueChapter(storyId, chapterId, text, model) {
        const headers = { 'X-User-Id': 'user_web_01' };
        const payload = {
            request: text,
            model,
            target_word_count: 1000,
            generation_config: { temperature: 0.8, max_output_tokens: 3000 }
        };
        const response = await this.repository.continueChapter(storyId, chapterId, payload, headers);
        return response.data;
    }

    /**
     * Analyze a specific chapter version.
     */
    async analyzeChapter(storyId, chapterId, versionId) {
        const payload = { version_id: versionId.toString(), action: 'REVISION_REQUESTED' };
        const response = await this.repository.analyzeChapter(storyId, chapterId, payload, { 'X-User-Id': 'user_web_01' });
        return response.data;
    }

    /**
     * Cancel the active job.
     */
    async cancelJob(jobId) {
        try {
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
            const headers = {
                'X-User-Id': 'user_web_01'
            };
            const result = await this.repository.cancelJob(jobId, headers);
            this.currentJobId = null;
            return result;
        } catch (error) {
            console.error("Service error cancelling job:", error);
            throw error;
        }
    }

    /**
     * Update version content with user edits.
     */
    async updateChapterVersionContent(storyId, chapterId, versionId, content) {
        const headers = { 'X-User-Id': 'user_web_01' };
        return this.repository.updateChapterVersionContent(storyId, chapterId, versionId, content, headers);
    }
}
