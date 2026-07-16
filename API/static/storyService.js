/**
 * STORY SERVICE (Model Layer - Business Logic)
 * Encapsulates workflows, state transitions, and SSE token streaming.
 */
class StoryService {
    constructor(repository) {
        this.repository = repository;
        this.currentJobId = null;
        this.eventSource = null;
    }

    /**
     * Get list of models for selection dropdown.
     */
    async loadModels() {
        try {
            const result = await this.repository.getModels();
            return result.data || [];
        } catch (error) {
            console.error("Service error loading models:", error);
            throw error;
        }
    }

    /**
     * Start the chapter generation process.
     */
    async startGeneration(storyId, formValues, onStatusChange, onTokenReceived, onComplete, onError) {
        try {
            const headers = {
                'Idempotency-Key': 'idemp_' + Date.now(),
                'X-Tenant-Id': 'tenant_web_01',
                'X-User-Id': 'user_web_01'
            };

            const payload = {
                request: formValues.request,
                model: formValues.model,
                mode: 'ASYNC',
                chapter: {
                    title: formValues.title,
                    target_word_count: parseInt(formValues.wordCount),
                    tone: formValues.tone
                },
                generation_config: {
                    temperature: 0.8,
                    max_output_tokens: 3000,
                    max_revision_attempts: 2,
                    auto_analyze: true
                },
                constraints: formValues.constraints
            };

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
            this.pollJobCompletion(jobId, onComplete, onError);
        };
    }

    /**
     * Fallback poll in case EventSource is closed or errored out early.
     */
    async pollJobCompletion(jobId, onComplete, onError) {
        let attempts = 0;
        const maxAttempts = 15;
        const interval = 2000;

        const check = async () => {
            try {
                const res = await this.repository.getJobStatus(jobId);
                const job = res.data;
                
                if (job.status === 'COMPLETED' || job.status === 'NEEDS_MANUAL_REVIEW') {
                    if (this.eventSource) this.eventSource.close();
                    onComplete(job.result);
                } else if (job.status === 'FAILED') {
                    if (this.eventSource) this.eventSource.close();
                    onError(new Error(job.error?.message || "Job failed."));
                } else if (attempts < maxAttempts) {
                    attempts++;
                    setTimeout(check, interval);
                } else {
                    onError(new Error("Polling timeout waiting for completion."));
                }
            } catch (err) {
                onError(err);
            }
        };

        setTimeout(check, interval);
    }

    /**
     * Approve the chapter version.
     */
    async approveChapter(storyId, chapterId, versionId) {
        return await this.repository.approveChapter(storyId, chapterId, versionId, 'user_web_01');
    }

    /**
     * Reject and submit feedback (Regenerate).
     */
    async regenerateChapter(storyId, chapterId, baseVersionId, feedback, modelName, onStatusChange, onTokenReceived, onComplete, onError) {
        try {
            const headers = {
                'Idempotency-Key': 'idemp_regen_' + Date.now(),
                'X-Tenant-Id': 'tenant_web_01',
                'X-User-Id': 'user_web_01'
            };

            const response = await this.repository.regenerateChapter(storyId, chapterId, baseVersionId, feedback, modelName, headers);
            onComplete(response.data);
        } catch (error) {
            onError(error);
        }
    }

    /**
     * Start the chapter generation process (Sync Mode).
     */
    async startGenerationSync(storyId, formValues, onStatusChange, onComplete, onError) {
        try {
            const headers = {
                'Idempotency-Key': 'idemp_sync_' + Date.now(),
                'X-Tenant-Id': 'tenant_web_01',
                'X-User-Id': 'user_web_01'
            };

            const payload = {
                request: formValues.request,
                model: formValues.model,
                mode: 'SYNC',
                chapter: {
                    title: formValues.title,
                    target_word_count: parseInt(formValues.wordCount),
                    tone: formValues.tone
                },
                generation_config: {
                    temperature: 0.8,
                    max_output_tokens: 3000,
                    max_revision_attempts: 2,
                    auto_analyze: true
                },
                constraints: formValues.constraints
            };

            onStatusChange({ status: 'PROCESSING', progress: 50, step: 'GENERATING' });

            const response = await this.repository.generateChapterSync(storyId, payload, headers);
            onComplete(response.data);
        } catch (error) {
            console.error("Service error starting sync generation:", error);
            onError(error);
        }
    }

    /**
     * Continue writing the chapter.
     */
    async continueChapter(storyId, chapterId, text, model, onComplete, onError) {
        try {
            const headers = {
                'X-User-Id': 'user_web_01'
            };
            const payload = {
                request: text,
                model: model,
                target_word_count: 1000,
                generation_config: {
                    temperature: 0.8,
                    max_output_tokens: 3000
                }
            };
            const response = await this.repository.continueChapter(storyId, chapterId, payload, headers);
            onComplete(response.data);
        } catch (error) {
            console.error("Service error continuing chapter:", error);
            onError(error);
        }
    }

    /**
     * Analyze a specific chapter version.
     */
    async analyzeChapter(storyId, chapterId, versionId, onComplete, onError) {
        try {
            const headers = {
                'X-User-Id': 'user_web_01'
            };
            const payload = {
                version_id: versionId.toString(),
                action: 'REVISION_REQUESTED'
            };
            const response = await this.repository.analyzeChapter(storyId, chapterId, payload, headers);
            onComplete(response.data);
        } catch (error) {
            console.error("Service error analyzing chapter:", error);
            onError(error);
        }
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
}
