/**
 * STORY CONTROLLER (Controller Layer - Event Handling & DOM Mapping)
 * Connects the View (index.html) controls to the Service logic, and updates DOM.
 */
class StoryController {
    constructor(service) {
        this.service = service;
        this.currentChapterId = null;
        this.currentVersionId = null;
        this.currentModel = null;
    }

    /**
     * Map DOM nodes and bind events.
     */
    init() {
        this.dom = {
            form: document.getElementById('generation-form'),
            storyId: document.getElementById('story-id'),
            modelSelect: document.getElementById('model-select'),
            chapterTitle: document.getElementById('chapter-title'),
            wordCount: document.getElementById('word-count'),
            toneSelect: document.getElementById('tone-select'),
            userPrompt: document.getElementById('user-prompt'),
            constraints: document.getElementById('constraints-list'),
            btnGenerate: document.getElementById('btn-generate'),
            
            progressContainer: document.getElementById('job-progress-container'),
            progressFill: document.getElementById('job-progress-fill'),
            jobStep: document.getElementById('job-step'),
            
            streamOutput: document.getElementById('stream-output'),
            
            analysisIdle: document.getElementById('analysis-idle'),
            analysisResults: document.getElementById('analysis-results'),
            analysisStatusBadge: document.getElementById('analysis-status-badge'),
            qualityScore: document.getElementById('quality-score'),
            issuesList: document.getElementById('issues-list'),
            
            memoryIdle: document.getElementById('memory-idle'),
            memoryResults: document.getElementById('memory-results'),
            memSummary: document.getElementById('mem-summary'),
            memFacts: document.getElementById('mem-facts'),
            
            actionPanel: document.getElementById('action-panel'),
            feedbackInput: document.getElementById('feedback-input'),
            btnApprove: document.getElementById('btn-approve'),
            btnRegenerate: document.getElementById('btn-regenerate'),
            btnContinue: document.getElementById('btn-continue'),
            btnAnalyze: document.getElementById('btn-analyze'),
            btnCancelJob: document.getElementById('btn-cancel-job'),
            generationMode: document.getElementById('generation-mode')
        };

        this.bindEvents();
        this.loadModels();
    }

    /**
     * Bind UI event listeners.
     */
    bindEvents() {
        this.dom.form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleStartGeneration();
        });

        this.dom.btnApprove.addEventListener('click', () => {
            this.handleApprove();
        });

        this.dom.btnRegenerate.addEventListener('click', () => {
            this.handleRegenerate();
        });

        if (this.dom.btnCancelJob) {
            this.dom.btnCancelJob.addEventListener('click', () => {
                this.handleCancelJob();
            });
        }

        if (this.dom.btnAnalyze) {
            this.dom.btnAnalyze.addEventListener('click', () => {
                this.handleAnalyze();
            });
        }

        if (this.dom.btnContinue) {
            this.dom.btnContinue.addEventListener('click', () => {
                this.handleContinue();
            });
        }
    }

    /**
     * Fetch and render models inside dropdown selector.
     */
    async loadModels() {
        try {
            const models = await this.service.loadModels();
            this.dom.modelSelect.innerHTML = '';
            
            if (models.length === 0) {
                this.dom.modelSelect.innerHTML = '<option value="">Không có mô hình nào</option>';
                return;
            }

            models.forEach(model => {
                const opt = document.createElement('option');
                opt.value = model.alias;
                opt.textContent = `${model.alias} (${model.provider})`;
                if (model.alias === 'claude-sonnet') {
                    opt.selected = true;
                }
                this.dom.modelSelect.appendChild(opt);
            });
        } catch (error) {
            this.dom.modelSelect.innerHTML = '<option value="">Lỗi tải danh sách mô hình</option>';
        }
    }

    /**
     * Start the generation pipeline.
     */
    handleStartGeneration() {
        const storyId = this.dom.storyId.value.trim();
        const formValues = {
            request: this.dom.userPrompt.value.trim(),
            model: this.dom.modelSelect.value,
            title: this.dom.chapterTitle.value.trim(),
            wordCount: this.dom.wordCount.value,
            tone: this.dom.toneSelect.value,
            constraints: this.dom.constraints.value.split('\n').map(c => c.trim()).filter(c => c.length > 0)
        };

        this.currentModel = formValues.model;

        // Reset View UI
        this.dom.streamOutput.innerText = '';
        this.dom.progressContainer.classList.remove('hidden');
        this.dom.progressFill.style.width = '0%';
        this.dom.jobStep.innerText = 'Đang chuẩn bị...';
        this.dom.actionPanel.classList.add('hidden');
        this.dom.analysisResults.classList.add('hidden');
        this.dom.analysisIdle.classList.remove('hidden');
        this.dom.qualityScore.classList.add('hidden');
        this.dom.memoryResults.classList.add('hidden');
        this.dom.memoryIdle.classList.remove('hidden');

        // Lock form during generation
        this.dom.btnGenerate.disabled = true;

        const mode = this.dom.generationMode ? this.dom.generationMode.value : 'ASYNC';

        if (mode === 'SYNC') {
            this.service.startGenerationSync(
                storyId,
                formValues,
                (state) => this.updateStatusView(state),
                (result) => this.handleGenerationComplete(result),
                (error) => this.handleGenerationError(error)
            );
        } else {
            this.service.startGeneration(
                storyId,
                formValues,
                (state) => this.updateStatusView(state),
                (token) => this.appendTokenView(token),
                (result) => this.handleGenerationComplete(result),
                (error) => this.handleGenerationError(error)
            );
        }
    }

    /**
     * Appends generated tokens in real-time.
     */
    appendTokenView(token) {
        this.dom.streamOutput.innerText += token;
        this.dom.streamOutput.scrollTop = this.dom.streamOutput.scrollHeight;
    }

    /**
     * Updates status HUD view during processing.
     */
    updateStatusView(state) {
        if (state.status) {
            this.dom.jobStep.innerText = state.step;
            this.dom.progressFill.style.width = `${state.progress}%`;
        }

        if (state.analysis) {
            this.renderAnalysisResult(state.analysis);
        }
    }

    /**
     * Render the Story Analyzer outcome.
     */
    renderAnalysisResult(analysis) {
        this.dom.analysisIdle.classList.add('hidden');
        this.dom.analysisResults.classList.remove('hidden');
        
        this.dom.qualityScore.innerText = analysis.score;
        this.dom.qualityScore.classList.remove('hidden');
        if (analysis.score >= 85) {
            this.dom.qualityScore.className = 'score-badge';
        } else {
            this.dom.qualityScore.className = 'score-badge low';
        }

        if (analysis.passed) {
            this.dom.analysisStatusBadge.innerText = 'Passed';
            this.dom.analysisStatusBadge.className = 'badge-status passed';
        } else {
            this.dom.analysisStatusBadge.innerText = 'Revision Req';
            this.dom.analysisStatusBadge.className = 'badge-status failed';
        }

        this.dom.issuesList.innerHTML = '';
        if (!analysis.issues || analysis.issues.length === 0) {
            this.dom.issuesList.innerHTML = '<div class="info-placeholder">Không tìm thấy lỗi logic nào. Bản viết hoàn hảo!</div>';
            return;
        }

        analysis.issues.forEach(issue => {
            const item = document.createElement('div');
            item.className = `issue-item ${issue.severity === 'HIGH' ? 'high' : ''}`;
            
            const title = document.createElement('div');
            title.className = 'issue-title';
            title.innerHTML = `<span>⚠️ ${issue.type}</span> <span class="badge" style="background: var(--color-${issue.severity === 'HIGH' ? 'error' : 'warning'});">${issue.severity}</span>`;
            
            const desc = document.createElement('div');
            desc.className = 'issue-desc';
            desc.innerText = issue.description;
            
            const suggest = document.createElement('div');
            suggest.className = 'issue-suggest';
            suggest.innerText = `💡 Gợi ý: ${issue.suggested_action}`;

            item.appendChild(title);
            item.appendChild(desc);
            item.appendChild(suggest);
            this.dom.issuesList.appendChild(item);
        });
    }

    /**
     * Complete Generation Handler.
     */
    handleGenerationComplete(result) {
        this.dom.btnGenerate.disabled = false;
        this.dom.progressContainer.classList.add('hidden');
        
        this.currentChapterId = result.chapter_id;
        this.currentVersionId = result.version_id;
        
        this.dom.streamOutput.innerText = result.content;
        
        if (result.analysis) {
            this.renderAnalysisResult(result.analysis);
        }

        this.dom.actionPanel.classList.remove('hidden');
    }

    /**
     * Error Generation Handler.
     */
    handleGenerationError(error) {
        this.dom.btnGenerate.disabled = false;
        this.dom.progressContainer.classList.add('hidden');
        alert(`Lỗi sinh chương truyện: ${error.message}`);
    }

    /**
     * Approve Version Handler (Triggers long-term memory updates).
     */
    async handleApprove() {
        const storyId = this.dom.storyId.value.trim();
        this.dom.btnApprove.disabled = true;

        try {
            const res = await this.service.approveChapter(storyId, this.currentChapterId, this.currentVersionId);
            
            this.dom.memoryIdle.classList.add('hidden');
            this.dom.memoryResults.classList.remove('hidden');
            
            this.dom.memSummary.innerText = "Chương truyện đã được duyệt thành công! Các sự kiện và chuyển đổi nhân vật đã được nén lưu trữ vào Story Memories của Vector DB.";
            
            const factsList = this.dom.memFacts;
            factsList.innerHTML = `
                <li>Lưu trữ thành công Chapter summary của chương mới vào Vector Store.</li>
                <li>Trích xuất các sự kiện chính trong chương làm Memory dài hạn cho các chương tiếp theo.</li>
            `;
            
            alert("Chúc mừng! Chương truyện đã được duyệt và lưu trữ ký ức hoàn tất.");
        } catch (error) {
            alert(`Lỗi duyệt chương truyện: ${error.message}`);
        } finally {
            this.dom.btnApprove.disabled = false;
        }
    }

    /**
     * Regenerate Version Handler.
     */
    async handleRegenerate() {
        const storyId = this.dom.storyId.value.trim();
        const feedback = this.dom.feedbackInput.value.trim();

        if (!feedback) {
            alert("Vui lòng nhập ý kiến phản hồi hoặc yêu cầu sửa đổi trước khi bấm Regenerate!");
            return;
        }

        this.dom.btnRegenerate.disabled = true;
        this.dom.progressContainer.classList.remove('hidden');
        this.dom.progressFill.style.width = '20%';
        this.dom.jobStep.innerText = 'Đang nạp phản hồi...';
        this.dom.actionPanel.classList.add('hidden');

        try {
            const result = await this.service.repository.regenerateChapter(
                storyId,
                this.currentChapterId,
                this.currentVersionId,
                feedback,
                this.currentModel,
                {
                    'X-User-Id': 'user_web_01',
                    'X-Tenant-Id': 'tenant_web_01'
                }
            );
            
            this.handleGenerationComplete(result.data);
            alert("Tái tạo bản nháp chương truyện thành công!");
        } catch (error) {
            alert(`Lỗi tái tạo chương truyện: ${error.message}`);
        } finally {
            this.dom.btnRegenerate.disabled = false;
        }
    }

    /**
     * Cancel an active generation job.
     */
    async handleCancelJob() {
        const jobId = this.service.currentJobId;
        if (!jobId) {
            alert("Không có tiến trình nào đang chạy.");
            return;
        }

        try {
            this.dom.btnCancelJob.disabled = true;
            this.dom.jobStep.innerText = 'Đang hủy tiến trình...';
            await this.service.cancelJob(jobId);
            this.dom.progressContainer.classList.add('hidden');
            this.dom.btnGenerate.disabled = false;
            alert("Đã hủy tiến trình sinh chương truyện thành công!");
        } catch (error) {
            alert(`Lỗi khi hủy tiến trình: ${error.message}`);
        } finally {
            if (this.dom.btnCancelJob) this.dom.btnCancelJob.disabled = false;
        }
    }

    /**
     * Manually request an independent quality check/analysis.
     */
    async handleAnalyze() {
        const storyId = this.dom.storyId.value.trim();
        if (!this.currentChapterId || !this.currentVersionId) {
            alert("Vui lòng sinh chương truyện trước khi đánh giá!");
            return;
        }

        this.dom.btnAnalyze.disabled = true;
        try {
            this.dom.analysisIdle.innerText = 'Đang chạy đánh giá...';
            this.dom.analysisIdle.classList.remove('hidden');
            this.dom.analysisResults.classList.add('hidden');

            await this.service.analyzeChapter(
                storyId,
                this.currentChapterId,
                this.currentVersionId,
                (analysisResult) => {
                    this.renderAnalysisResult(analysisResult);
                    this.dom.btnAnalyze.disabled = false;
                    alert("Đánh giá chất lượng thành công!");
                },
                (error) => {
                    this.dom.analysisIdle.innerText = `Lỗi: ${error.message}`;
                    this.dom.btnAnalyze.disabled = false;
                    alert(`Lỗi đánh giá chương truyện: ${error.message}`);
                }
            );
        } catch (error) {
            this.dom.btnAnalyze.disabled = false;
            alert(`Lỗi: ${error.message}`);
        }
    }

    /**
     * Continue writing the chapter content.
     */
    async handleContinue() {
        const storyId = this.dom.storyId.value.trim();
        const text = this.dom.feedbackInput.value.trim();

        if (!text) {
            alert("Vui lòng nhập định hướng/yêu cầu viết tiếp vào ô phản hồi!");
            return;
        }

        if (!this.currentChapterId) {
            alert("Không tìm thấy chương truyện hiện tại để viết tiếp.");
            return;
        }

        this.dom.btnContinue.disabled = true;
        this.dom.progressContainer.classList.remove('hidden');
        this.dom.progressFill.style.width = '30%';
        this.dom.jobStep.innerText = 'Đang chuẩn bị viết tiếp...';
        this.dom.actionPanel.classList.add('hidden');

        try {
            await this.service.continueChapter(
                storyId,
                this.currentChapterId,
                text,
                this.currentModel || 'claude-sonnet',
                (result) => {
                    this.dom.progressContainer.classList.add('hidden');
                    this.dom.btnContinue.disabled = false;
                    
                    this.currentVersionId = result.version_id;
                    this.dom.streamOutput.innerText = result.content;
                    this.dom.actionPanel.classList.remove('hidden');
                    this.dom.feedbackInput.value = '';
                    alert("Đã sinh phần viết tiếp thành công!");
                },
                (error) => {
                    this.dom.progressContainer.classList.add('hidden');
                    this.dom.btnContinue.disabled = false;
                    this.dom.actionPanel.classList.remove('hidden');
                    alert(`Lỗi viết tiếp chương truyện: ${error.message}`);
                }
            );
        } catch (error) {
            this.dom.progressContainer.classList.add('hidden');
            this.dom.btnContinue.disabled = false;
            this.dom.actionPanel.classList.remove('hidden');
            alert(`Lỗi: ${error.message}`);
        }
    }
}
