/**
 * STORY CONTROLLER (Controller Layer - Core Event Dispatcher)
 * Responsibilities:
 * - Coordinates StoryWorkspace, StoryExporter, and StoryAnalysisRenderer.
 * - Handles DOM events, Generation pipeline, and Inline Editor.
 */
class StoryController {
    constructor(service) {
        this.service = service;
        this.workspace = new StoryWorkspace();
        this.currentModel = null;
        this.isEditingMode = false;
        this.chapterSource = '';
        this.archiveVisibleCount = 20;
    }

    init() {
        this.bindDOM();
        this.initTheme();
        this.workspace.init();
        this.syncWorkspaceUI();
        this.bindEvents();
        this.loadModels();
        this.loadPersistedChats();
        this.updateWordCount();
        this.toggleEditMode(false);
    }

    bindDOM() {
        const get = id => document.getElementById(id);
        this.dom = {
            sidebar: get('sidebar'), btnTopbarSidebarToggle: get('btn-topbar-sidebar-toggle'),
            btnThemeToggle: get('btn-theme-toggle'), themeIcon: get('theme-icon'), themeLabel: get('theme-label'),
            btnCreateStory: get('btn-create-story'), storiesList: get('stories-list'),
            btnStoryArchive: get('btn-story-archive'), storyArchiveDialog: get('story-archive-dialog'),
            storyArchiveList: get('story-archive-list'), btnCloseStoryArchive: get('btn-close-story-archive'),
            chaptersHistoryList: get('chapters-history-list'), btnCreateChapter: get('btn-create-chapter'),
            btnChapterArchive: get('btn-chapter-archive'), chapterArchiveDialog: get('chapter-archive-dialog'),
            chapterArchiveTitle: get('chapter-archive-title'), chapterArchiveSearch: get('chapter-archive-search'),
            chapterArchiveSort: get('chapter-archive-sort'), chapterArchiveCount: get('chapter-archive-count'),
            chapterArchiveList: get('chapter-archive-list'), btnCloseChapterArchive: get('btn-close-chapter-archive'),
            btnLoadMoreChapters: get('btn-load-more-chapters'), chapterNavigation: get('chapter-navigation'),
            btnPreviousChapter: get('btn-previous-chapter'), btnNextChapter: get('btn-next-chapter'),
            btnCreateSubthread: get('btn-create-subthread'), chapterConfig: get('chapter-config'),
            subthreadsList: get('subthreads-list'), newStoryDialog: get('new-story-dialog'),
            newStoryForm: get('new-story-form'), modalStoryTitle: get('modal-story-title'),
            modalMasterTone: get('modal-master-tone'), modalMasterOutline: get('modal-master-outline'),
            btnCloseNewStory: get('btn-close-new-story'), btnCancelNewStory: get('btn-cancel-new-story'),
            btnStoryMindmap: get('btn-story-mindmap'), mindmapDialog: get('story-mindmap-dialog'),
            mindmapContent: get('story-mindmap-content'), btnCloseMindmap: get('btn-close-mindmap'),
            btnLoreFinder: get('btn-lore-finder'), loreDialog: get('lore-finder-dialog'),
            loreForm: get('lore-search-form'), loreQuery: get('lore-query'), loreResults: get('lore-results'),
            btnSearchLore: get('btn-search-lore'), btnCloseLore: get('btn-close-lore'),
            form: get('generation-form'), storyId: get('story-id'), modelSelect: get('model-select'),
            chapterTitle: get('chapter-title'), wordCount: get('word-count'),
            chapterToneOverride: get('chapter-tone-override'), userPrompt: get('user-prompt'),
            constraints: get('constraints-list'), btnGenerate: get('btn-generate'),
            activeStoryName: get('active-story-name'),
            activeTitle: get('active-title'), activeModelBadge: get('active-model-badge'),
            chapterStatusBadge: get('chapter-status-badge'), userPromptRow: get('user-prompt-row'),
            progressContainer: get('job-progress-container'), progressFill: get('job-progress-fill'),
            jobStep: get('job-step'), btnCancelJob: get('btn-cancel-job'),
            welcomeContainer: get('welcome-container'), feedThread: get('feed-thread'), chatThread: get('chat-thread'),
            chatScrollFeed: get('chat-scroll-feed'), chatInputContainer: get('chat-input-container'),
            userPromptDisplay: get('user-prompt-display'), streamOutput: get('stream-output'),
            liveWordCount: get('live-word-count'), btnToggleEdit: get('btn-toggle-edit'),
            editBtnText: get('edit-btn-text'), editIndicator: get('edit-indicator'),
            btnSaveEdit: get('btn-save-edit'), btnCopyText: get('btn-copy-text'),
            btnExport: get('btn-export'), exportMenu: get('export-menu'), exportTxt: get('export-txt'),
            exportDoc: get('export-doc'), exportPdf: get('export-pdf'),
            analysisIdle: get('analysis-idle'), analysisResults: get('analysis-results'),
            analysisStatusBadge: get('analysis-status-badge'), qualityScore: get('quality-score'),
            issuesList: get('issues-list'), btnAnalyze: get('btn-analyze'),
            memoryIdle: get('memory-idle'), memoryResults: get('memory-results'),
            memSummary: get('mem-summary'), memFacts: get('mem-facts'),
            actionPanel: get('action-panel'), feedbackInput: get('feedback-input'),
            btnApprove: get('btn-approve'), btnRegenerate: get('btn-regenerate'), btnContinue: get('btn-continue'),
            sendText: get('send-text')
        };
    }

    initTheme() {
        const savedTheme = localStorage.getItem('ai_story_theme') || 'dark';
        document.documentElement.setAttribute('data-theme', savedTheme);
        this.updateThemeButton(savedTheme);
    }

    updateThemeButton(theme) {
        const isDark = theme === 'dark';
        if (this.dom.themeIcon) this.dom.themeIcon.innerText = isDark ? '🌙' : '☀️';
        if (this.dom.themeLabel) this.dom.themeLabel.innerText = isDark ? 'Tối' : 'Sáng';
        const action = `Chuyển sang chế độ ${isDark ? 'sáng' : 'tối'}`;
        this.dom.btnThemeToggle.title = action;
        this.dom.btnThemeToggle.setAttribute('aria-label', action);
    }

    toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('ai_story_theme', newTheme);
        this.updateThemeButton(newTheme);
    }

    syncWorkspaceUI() {
        const activeStory = this.workspace.getActiveStory();
        if (!activeStory) return;
        this.dom.storyId.value = activeStory.id;
        this.dom.activeStoryName.innerText = activeStory.title;
        const mode = this.workspace.getMode();
        const isChat = mode === 'chat';
        const isChapter = mode === 'chapter';
        this.dom.chapterConfig.classList.toggle('hidden', mode !== 'new-chapter');
        this.dom.chatInputContainer.classList.toggle('hidden', isChapter);
        this.dom.userPromptRow.classList.toggle('hidden', isChapter);
        this.dom.chatScrollFeed.classList.toggle('chapter-reading-mode', isChapter);
        this.dom.chapterStatusBadge.classList.toggle('hidden', !isChapter);
        const createChapterLabel = this.dom.btnCreateChapter.querySelector('span');
        if (createChapterLabel) createChapterLabel.textContent = '📖 Tạo Chương Mới';
        if (isChapter) {
            const chapter = activeStory.chapters?.find(item => item.chapterId === this.workspace.currentChapterId);
            this.updateChapterStatus(chapter?.status);
        }

        if (isChat) {
            if (this.dom.sendText) this.dom.sendText.innerText = "Gửi tin nhắn";
            this.dom.userPrompt.placeholder = "Nhập câu hỏi hoặc trao đổi với AI về kịch bản... (Enter để gửi, Shift+Enter để xuống dòng)";
        } else {
            if (this.dom.sendText) this.dom.sendText.innerText = "Gửi yêu cầu";
            this.dom.userPrompt.placeholder = "Nhập yêu cầu nội dung chương mới... (Enter để gửi, Shift+Enter để xuống dòng)";
        }

        this.workspace.renderStoriesList(this.dom.storiesList, (id) => {
            this.workspace.selectStory(id);
            this.startNewChapter();
            this.loadPersistedChats(id);
        }, (id, title) => this.archiveStory(id, title));
        const archivedStoryCount = this.workspace.getArchivedStories().length;
        this.dom.btnStoryArchive.classList.toggle('hidden', archivedStoryCount === 0);
        this.dom.btnStoryArchive.textContent = `Kho lưu trữ · ${archivedStoryCount}`;
        this.workspace.renderSubthreadsList(this.dom.subthreadsList, (id) => {
            const thread = this.workspace.selectSubthread(id);
            if (thread) { this.showActiveChat(); this.syncWorkspaceUI(); }
        }, (id, title) => this.deleteChat(id, title));
        const chapters = this.workspace.getChapters();
        this.workspace.renderChaptersList(
            this.dom.chaptersHistoryList,
            chap => this.loadChapterIntoView(chap),
            chap => this.deleteChapter(chap),
            (chap, title) => this.renameChapter(chap, title),
            chapters.slice(0, this.workspace.recentChapterLimit)
        );
        this.dom.btnChapterArchive.classList.toggle('hidden', chapters.length <= this.workspace.recentChapterLimit);
        this.dom.btnChapterArchive.textContent = `Kho chương · ${chapters.length}`;
        this.updateChapterNavigation();
    }

    openNewStoryModal() {
        if (this.dom.newStoryDialog) {
            this.dom.modalStoryTitle.value = `Truyện ${this.workspace.stories.length + 1}`;
            this.dom.modalMasterTone.value = "Thô mộc, đời thực, bộc trực, không dùng từ ngữ sến sẩm AI";
            this.dom.modalMasterOutline.value = "";
            this.dom.newStoryDialog.showModal();
        }
    }

    handleCreateNewStorySubmit() {
        this.workspace.createStory(this.dom.modalStoryTitle.value.trim(), this.dom.modalMasterTone.value.trim(), this.dom.modalMasterOutline.value.trim());
        this.dom.newStoryDialog.close();
        this.startNewChapter();
    }

    async createNewSubthread() {
        const activeStory = this.workspace.getActiveStory();
        const count = (activeStory?.subthreads?.length || 0) + 1;
        const title = `Chat ${count} - Thử Nghiệm Kịch Bản`;
        const subthread = this.workspace.createSubthread(title);
        if (subthread) {
            this.showActiveChat();
            this.syncWorkspaceUI();
            try {
                await this.service.saveChatThread(this.workspace.currentStoryId, subthread);
            } catch (error) {
                console.warn(`Chat đã tạo trên máy nhưng chưa lưu được vào database: ${error.message || error}`);
            }
        }
    }

    async loadPersistedChats(storyId = this.workspace.currentStoryId) {
        const story = this.workspace.stories.find(item => item.id === storyId);
        if (!story) return;
        const localThreads = story.subthreads || [];
        try {
            const persistedThreads = await this.service.loadChats(storyId);
            if (this.workspace.currentStoryId !== storyId) return;
            if (persistedThreads.length) {
                this.workspace.replaceSubthreads(storyId, persistedThreads);
            } else if (localThreads.length) {
                await Promise.all(localThreads.map(thread => this.service.saveChatThread(storyId, thread)));
            }
            this.syncWorkspaceUI();
        } catch (error) {
            console.error('Không thể đồng bộ chat với database:', error);
        }
    }

    startNewChapter() {
        this.workspace.currentSubthreadId = null;
        this.workspace.currentChapterId = null;
        this.workspace.currentVersionId = null;
        this.dom.activeTitle.innerText = 'Chương mới';
        this.resetNewChapterView();
        this.syncWorkspaceUI();
    }

    archiveStory(storyId, title) {
        if (this.workspace.getActiveStories().length <= 1) {
            alert('Cần giữ lại ít nhất một bộ truyện đang hoạt động. Hãy tạo truyện mới trước khi lưu trữ truyện này.');
            return;
        }
        if (!confirm(`Lưu trữ "${title}"? Toàn bộ chương, chat và ký ức vẫn được giữ nguyên.`)) return;
        const wasActive = this.workspace.currentStoryId === storyId;
        if (!this.workspace.archiveStory(storyId)) return;
        if (wasActive) {
            const nextStoryId = this.workspace.currentStoryId;
            this.startNewChapter();
            this.loadPersistedChats(nextStoryId);
        } else {
            this.syncWorkspaceUI();
        }
    }

    openStoryArchive() {
        this.renderStoryArchive();
        this.dom.storyArchiveDialog.showModal();
    }

    renderStoryArchive() {
        this.workspace.renderArchivedStoriesList(this.dom.storyArchiveList, storyId => {
            if (!this.workspace.restoreStory(storyId)) return;
            this.renderStoryArchive();
            this.syncWorkspaceUI();
        });
    }

    async deleteChat(threadId, title) {
        if (!confirm(`Xóa chat "${title}"? Nội dung chat này sẽ không còn được dùng để tạo chương.`)) return;
        try {
            await this.service.deleteChatThread(this.workspace.currentStoryId, threadId);
            const wasActive = this.workspace.currentSubthreadId === threadId;
            this.workspace.deleteSubthread(threadId);
            if (wasActive) this.startNewChapter();
            else this.syncWorkspaceUI();
        } catch (error) {
            alert(`Không thể xóa chat khỏi database: ${error.message || error}`);
        }
    }

    async deleteChapter(chapter) {
        const title = chapter.title || 'chương này';
        if (!confirm(`Xóa "${title}"? Bản thảo, phiên bản và ký ức của chương sẽ bị xóa.`)) return;
        try {
            await this.service.deleteChapter(this.workspace.currentStoryId, chapter.chapterId);
            const wasActive = this.workspace.currentChapterId === chapter.chapterId;
            this.workspace.deleteChapter(chapter.chapterId);
            if (wasActive) this.startNewChapter();
            else this.syncWorkspaceUI();
            if (this.dom.chapterArchiveDialog.open) this.renderChapterArchive();
        } catch (error) {
            alert(`Không thể xóa chương: ${error.message || error}`);
        }
    }

    async renameChapter(chapter, title) {
        try {
            await this.service.renameChapter(this.workspace.currentStoryId, chapter.chapterId, title);
            this.workspace.renameChapter(chapter.chapterId, title);
            if (this.workspace.currentChapterId === chapter.chapterId) this.dom.activeTitle.textContent = title;
            this.syncWorkspaceUI();
            if (this.dom.chapterArchiveDialog.open) this.renderChapterArchive();
        } catch (error) {
            alert(`Không thể đổi tên chương: ${error.message || error}`);
            this.syncWorkspaceUI();
        }
    }

    showActiveChat() {
        const thread = this.workspace.getSubthread();
        if (!thread) return;
        this.dom.activeTitle.innerText = `[Chat] ${thread.title}`;
        this.dom.welcomeContainer.classList.add('hidden');
        this.dom.feedThread.classList.add('hidden');
        this.dom.chatThread.classList.remove('hidden');
        this.renderChatThread(thread);
    }

    renderChatThread(thread = this.workspace.getSubthread(), isTyping = false) {
        this.dom.chatThread.replaceChildren();
        if (!thread?.messages.length) {
            const empty = document.createElement('p');
            empty.className = 'info-placeholder chat-empty';
            empty.textContent = 'Chat riêng để phát triển ý tưởng. Nội dung trao đổi sẽ được đưa vào ngữ cảnh khi bạn tạo chương.';
            this.dom.chatThread.appendChild(empty);
            return;
        }
        thread.messages.forEach((message, messageIndex) => {
            const row = document.createElement('div');
            row.className = `chat-message ${message.role}`;
            const avatar = document.createElement('div');
            avatar.className = `avatar ${message.role === 'user' ? 'user-avatar' : 'ai-avatar'}`;
            avatar.textContent = message.role === 'user' ? '👤' : '✨';
            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';
            StoryController.renderBoldText(bubble, message.content);
            if (message.role === 'assistant') {
                const exported = this.workspace.getActiveStory()?.chapters?.find(chapter =>
                    chapter.sourceThreadId === thread.id
                    && chapter.sourceMessageIndex === messageIndex
                );
                const action = document.createElement('button');
                action.type = 'button';
                action.className = 'chat-export-chapter';
                action.disabled = Boolean(exported);
                action.textContent = exported ? `✓ Đã xuất: ${exported.title}` : '📖 Chốt thành chương';
                action.addEventListener('click', () =>
                    this.exportChatMessageAsChapter(thread, message, messageIndex, action)
                );
                bubble.appendChild(action);
            }
            row.append(avatar, bubble);
            this.dom.chatThread.appendChild(row);
        });
        if (isTyping) {
            const row = document.createElement('div');
            row.className = 'chat-message assistant chat-typing';
            const avatar = document.createElement('div');
            avatar.className = 'avatar ai-avatar';
            avatar.textContent = '✨';
            const bubble = document.createElement('div');
            bubble.className = 'message-bubble typing-bubble';
            bubble.setAttribute('aria-label', 'AI đang trả lời');
            bubble.append(document.createElement('span'), document.createElement('span'), document.createElement('span'));
            row.append(avatar, bubble);
            this.dom.chatThread.appendChild(row);
        }
        this.dom.chatThread.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }

    async exportChatMessageAsChapter(thread, message, messageIndex, button) {
        const storyId = this.workspace.currentStoryId;
        const title = `Chương ${this.workspace.getChapters().length + 1}`;
        try {
            button.disabled = true;
            button.textContent = 'Đang xuất...';
            const chapter = await this.service.exportChatChapter(storyId, {
                title,
                content: message.content,
                model: this.dom.modelSelect.value,
                thread_id: thread.id,
                message_index: messageIndex
            });
            this.workspace.saveChapterToCurrentStory(chapter, storyId);
            if (this.workspace.currentStoryId === storyId) {
                this.syncWorkspaceUI();
                this.renderChatThread(this.workspace.getSubthread(thread.id, storyId));
            }
        } catch (error) {
            alert(`Không thể xuất câu trả lời thành chương: ${error.message || error}`);
            button.disabled = false;
            button.textContent = '📖 Chốt thành chương';
        }
    }

    async loadChapterIntoView(chap) {
        const storyId = this.workspace.currentStoryId;
        this.workspace.currentSubthreadId = null;
        this.workspace.currentChapterId = chap.chapterId;
        this.dom.activeTitle.innerText = chap.title || 'Chương đã lưu';
        this.dom.welcomeContainer.classList.add('hidden');
        this.dom.chatThread.classList.add('hidden');
        this.dom.feedThread.classList.remove('hidden');
        if (chap.content == null) {
            this.setChapterContent('Đang tải nội dung chương...', false);
            this.dom.actionPanel.classList.add('hidden');
            try {
                Object.assign(chap, await this.service.getChapter(storyId, chap.chapterId));
                if (this.workspace.currentStoryId !== storyId || this.workspace.currentChapterId !== chap.chapterId) return;
                this.workspace.saveChapterToCurrentStory(chap, storyId);
            } catch (error) {
                this.setChapterContent('');
                alert(`Không thể tải chương: ${error.message || error}`);
                return;
            }
        }
        this.workspace.currentVersionId = chap.versionId;
        this.currentModel = chap.model || this.dom.modelSelect.value;
        this.setChapterContent(chap.content || '');
        this.dom.actionPanel.classList.remove('hidden');
        this.updateWordCount();
        this.toggleEditMode(false);
        this.syncWorkspaceUI();
    }

    static splitBoldText(text) {
        return String(text || '').split(/(\*\*[^*\n]+\*\*)/g).filter(Boolean);
    }

    static renderBoldText(element, text) {
        const fragment = document.createDocumentFragment();
        StoryController.splitBoldText(text).forEach(part => {
            if (part.startsWith('**') && part.endsWith('**')) {
                const strong = document.createElement('strong');
                strong.textContent = part.slice(2, -2);
                fragment.appendChild(strong);
            } else {
                fragment.appendChild(document.createTextNode(part));
            }
        });
        element.replaceChildren(fragment);
    }

    setChapterContent(content, formatted = true) {
        this.chapterSource = String(content || '');
        if (formatted) StoryController.renderBoldText(this.dom.streamOutput, this.chapterSource);
        else this.dom.streamOutput.innerText = this.chapterSource;
    }

    updateChapterStatus(status = 'DRAFT') {
        const labels = {
            APPROVED: 'Đã duyệt',
            EDITED: 'Đã lưu',
            EDITING: 'Đang sửa',
            COMPLETED: 'Bản nháp',
            READY_FOR_REVIEW: 'Bản nháp',
            DRAFT: 'Bản nháp'
        };
        this.dom.chapterStatusBadge.textContent = labels[status] || 'Bản nháp';
        this.dom.chapterStatusBadge.dataset.status = status;
    }

    updateChapterNavigation() {
        const chapterId = this.workspace.currentChapterId;
        this.dom.chapterNavigation.classList.toggle('hidden', !chapterId);
        if (!chapterId) return;
        this.dom.btnPreviousChapter.disabled = !this.workspace.getAdjacentChapter(chapterId, -1);
        this.dom.btnNextChapter.disabled = !this.workspace.getAdjacentChapter(chapterId, 1);
    }

    loadAdjacentChapter(offset) {
        const chapter = this.workspace.getAdjacentChapter(this.workspace.currentChapterId, offset);
        if (chapter) this.loadChapterIntoView(chapter);
    }

    openChapterArchive() {
        const story = this.workspace.getActiveStory();
        if (!story) return;
        this.archiveVisibleCount = 20;
        this.dom.chapterArchiveSearch.value = '';
        this.dom.chapterArchiveSort.value = 'oldest';
        this.dom.chapterArchiveTitle.textContent = `Kho chương · ${story.title}`;
        this.renderChapterArchive();
        this.dom.chapterArchiveDialog.showModal();
        this.dom.chapterArchiveSearch.focus();
    }

    renderChapterArchive() {
        const chapters = this.workspace.getChapters({
            query: this.dom.chapterArchiveSearch.value,
            oldestFirst: this.dom.chapterArchiveSort.value === 'oldest'
        });
        this.dom.chapterArchiveCount.textContent = `${chapters.length} chương`;
        this.workspace.renderChaptersList(
            this.dom.chapterArchiveList,
            chapter => {
                this.loadChapterIntoView(chapter);
                this.dom.chapterArchiveDialog.close();
            },
            chapter => this.deleteChapter(chapter),
            (chapter, title) => this.renameChapter(chapter, title),
            chapters.slice(0, this.archiveVisibleCount),
            'Không tìm thấy chương phù hợp.'
        );
        this.dom.btnLoadMoreChapters.classList.toggle('hidden', chapters.length <= this.archiveVisibleCount);
    }

    openStoryMindmap() {
        const story = this.workspace.getActiveStory();
        if (!story) return;
        StoryExplorer.renderMindmap(this.dom.mindmapContent, story, chap => { this.loadChapterIntoView(chap); this.dom.mindmapDialog.close(); });
        this.dom.mindmapDialog.showModal();
    }

    openLoreFinder() {
        this.dom.loreDialog.showModal();
        this.dom.loreQuery.focus();
    }

    async handleLoreSearch() {
        const query = this.dom.loreQuery.value.trim();
        if (query.length < 2) return;
        this.dom.btnSearchLore.disabled = true;
        this.dom.loreResults.innerHTML = '<p class="story-tool-empty">Đang tìm trong ký ức...</p>';
        try {
            const memories = await this.service.searchLore(this.workspace.currentStoryId, query);
            StoryExplorer.renderLoreResults(this.dom.loreResults, memories);
        } catch (error) { this.dom.loreResults.textContent = `Lỗi: ${error.message}`; }
        finally { this.dom.btnSearchLore.disabled = false; }
    }

    bindEvents() {
        if (this.dom.btnTopbarSidebarToggle) this.dom.btnTopbarSidebarToggle.addEventListener('click', () => this.dom.sidebar.classList.toggle('collapsed'));
        if (this.dom.btnThemeToggle) this.dom.btnThemeToggle.addEventListener('click', () => this.toggleTheme());
        if (this.dom.btnCreateStory) this.dom.btnCreateStory.addEventListener('click', () => this.openNewStoryModal());
        this.dom.btnStoryArchive.addEventListener('click', () => this.openStoryArchive());
        this.dom.btnCloseStoryArchive.addEventListener('click', () => this.dom.storyArchiveDialog.close());
        if (this.dom.newStoryForm) this.dom.newStoryForm.addEventListener('submit', (e) => { e.preventDefault(); this.handleCreateNewStorySubmit(); });
        if (this.dom.btnCloseNewStory) this.dom.btnCloseNewStory.addEventListener('click', () => this.dom.newStoryDialog.close());
        if (this.dom.btnCancelNewStory) this.dom.btnCancelNewStory.addEventListener('click', () => this.dom.newStoryDialog.close());
        if (this.dom.btnCreateSubthread) this.dom.btnCreateSubthread.addEventListener('click', () => this.createNewSubthread());
        if (this.dom.btnCreateChapter) this.dom.btnCreateChapter.addEventListener('click', () => this.startNewChapter());
        this.dom.btnChapterArchive.addEventListener('click', () => this.openChapterArchive());
        this.dom.btnCloseChapterArchive.addEventListener('click', () => this.dom.chapterArchiveDialog.close());
        this.dom.chapterArchiveSearch.addEventListener('input', () => { this.archiveVisibleCount = 20; this.renderChapterArchive(); });
        this.dom.chapterArchiveSort.addEventListener('change', () => { this.archiveVisibleCount = 20; this.renderChapterArchive(); });
        this.dom.btnLoadMoreChapters.addEventListener('click', () => { this.archiveVisibleCount += 20; this.renderChapterArchive(); });
        this.dom.btnPreviousChapter.addEventListener('click', () => this.loadAdjacentChapter(-1));
        this.dom.btnNextChapter.addEventListener('click', () => this.loadAdjacentChapter(1));

        this.dom.btnStoryMindmap.addEventListener('click', () => this.openStoryMindmap());
        this.dom.btnCloseMindmap.addEventListener('click', () => this.dom.mindmapDialog.close());
        this.dom.btnLoreFinder.addEventListener('click', () => this.openLoreFinder());
        this.dom.btnCloseLore.addEventListener('click', () => this.dom.loreDialog.close());
        this.dom.loreForm.addEventListener('submit', (e) => { e.preventDefault(); this.handleLoreSearch(); });

        this.dom.userPrompt.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.dom.form.requestSubmit ? this.dom.form.requestSubmit() : this.dom.form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
            }
        });
        this.dom.userPrompt.addEventListener('input', () => {
            this.dom.userPrompt.style.height = 'auto';
            this.dom.userPrompt.style.height = `${Math.min(this.dom.userPrompt.scrollHeight, 150)}px`;
            this.dom.userPrompt.style.overflowY = this.dom.userPrompt.scrollHeight > 150 ? 'auto' : 'hidden';
        });

        this.dom.form.addEventListener('submit', (e) => { e.preventDefault(); this.handleStartGeneration(); });
        this.dom.streamOutput.addEventListener('input', () => {
            this.chapterSource = this.dom.streamOutput.innerText;
            this.updateWordCount();
            if (this.workspace.currentChapterId) this.updateChapterStatus('EDITING');
        });
        this.dom.btnToggleEdit.addEventListener('click', () => this.toggleEditMode());
        this.dom.btnSaveEdit.addEventListener('click', () => this.handleSaveEdits());
        this.dom.btnCopyText.addEventListener('click', () => this.handleCopyText());

        if (this.dom.btnExport) {
            this.dom.btnExport.addEventListener('click', (e) => { e.stopPropagation(); this.dom.exportMenu.classList.toggle('hidden'); });
            document.addEventListener('click', () => this.dom.exportMenu.classList.add('hidden'));
        }
        if (this.dom.exportTxt) this.dom.exportTxt.addEventListener('click', () => StoryExporter.exportTxt(this.dom.streamOutput.innerText, this.dom.activeTitle.innerText));
        if (this.dom.exportDoc) this.dom.exportDoc.addEventListener('click', () => StoryExporter.exportDoc(this.dom.streamOutput.innerText, this.dom.activeTitle.innerText));
        if (this.dom.exportPdf) this.dom.exportPdf.addEventListener('click', () => StoryExporter.exportPdf(this.dom.streamOutput.innerText));

        this.dom.btnApprove.addEventListener('click', () => this.handleApprove());
        this.dom.btnRegenerate.addEventListener('click', () => this.handleRegenerate());
        if (this.dom.btnCancelJob) this.dom.btnCancelJob.addEventListener('click', () => this.handleCancelJob());
        if (this.dom.btnAnalyze) this.dom.btnAnalyze.addEventListener('click', () => this.handleAnalyze());
        if (this.dom.btnContinue) this.dom.btnContinue.addEventListener('click', () => this.handleContinue());
    }

    updateWordCount() {
        const text = this.dom.streamOutput.innerText || '';
        const words = text.trim() ? text.trim().split(/\s+/).length : 0;
        this.dom.liveWordCount.innerText = `📊 ${words} từ | ${text.length} ký tự`;
    }

    toggleEditMode(forceState = null) {
        const wasEditing = this.isEditingMode;
        this.isEditingMode = forceState !== null ? forceState : !this.isEditingMode;
        if (wasEditing) this.chapterSource = this.dom.streamOutput.innerText;
        this.setChapterContent(this.chapterSource, !this.isEditingMode);
        this.dom.streamOutput.contentEditable = String(this.isEditingMode);
        if (this.isEditingMode) {
            this.dom.streamOutput.classList.add('editing-active');
            this.dom.editBtnText.innerText = 'Khóa lại';
            this.dom.editIndicator.classList.remove('hidden');
            this.dom.btnSaveEdit.classList.remove('hidden');
            this.dom.streamOutput.focus();
        } else {
            this.dom.streamOutput.classList.remove('editing-active');
            this.dom.editBtnText.innerText = 'Sửa trực tiếp';
            this.dom.editIndicator.classList.add('hidden');
            this.dom.btnSaveEdit.classList.add('hidden');
        }
    }

    async handleSaveEdits() {
        const storyId = this.workspace.currentStoryId;
        const content = this.chapterSource;
        if (!this.workspace.currentChapterId || !this.workspace.currentVersionId) return alert("Chưa có chương truyện nào!");
        try {
            this.dom.btnSaveEdit.disabled = true;
            await this.service.updateChapterVersionContent(storyId, this.workspace.currentChapterId, this.workspace.currentVersionId, content);
            this.workspace.saveChapterToCurrentStory({ chapterId: this.workspace.currentChapterId, versionId: this.workspace.currentVersionId, title: this.dom.activeTitle.innerText, content, status: 'EDITED' });
            this.updateChapterStatus('EDITED');
            this.syncWorkspaceUI();
            alert("✅ Đã lưu bản sửa vào CSDL!");
        } catch (error) { alert(`Lỗi: ${error.message}`); }
        finally { this.dom.btnSaveEdit.disabled = false; }
    }

    handleCopyText() {
        const text = this.dom.streamOutput.innerText;
        if (!text) return alert("Chưa có nội dung!");
        navigator.clipboard.writeText(text).then(() => alert("📋 Đã sao chép vào Clipboard!")).catch(err => alert(`Lỗi: ${err}`));
    }

    resetNewChapterView() {
        this.dom.welcomeContainer.classList.remove('hidden');
        this.dom.feedThread.classList.add('hidden');
        this.dom.chatThread.classList.add('hidden');
        this.setChapterContent('');
        this.dom.userPrompt.value = '';
        this.dom.feedbackInput.value = '';
        this.dom.userPrompt.focus();
        this.updateWordCount();
    }

    async loadModels() {
        try {
            const models = await this.service.loadModels();
            this.dom.modelSelect.innerHTML = models.length === 0 ? '<option value="">Không có mô hình nào</option>' : '';
            models.filter(model => model.enabled).forEach(model => {
                const opt = document.createElement('option');
                opt.value = model.alias;
                opt.textContent = `${model.alias} (${model.provider})`;
                if (model.alias === 'gemini-long-context' || model.alias === 'claude-sonnet') opt.selected = true;
                this.dom.modelSelect.appendChild(opt);
            });
        } catch (error) { this.dom.modelSelect.innerHTML = '<option value="">Lỗi tải mô hình</option>'; }
    }

    handleStartGeneration() {
        const storyId = this.workspace.currentStoryId;
        const promptText = this.dom.userPrompt.value.trim();
        if (promptText.length < 5) {
            this.dom.userPrompt.setCustomValidity('Yêu cầu cần ít nhất 5 ký tự.');
            this.dom.userPrompt.reportValidity();
            this.dom.userPrompt.setCustomValidity('');
            return;
        }
        if (this.workspace.currentSubthreadId) {
            this.handleChatMessage(promptText);
            return;
        }
        const titleText = this.dom.chapterTitle.value.trim() || 'Chương không tiêu đề';
        const activeStory = this.workspace.getActiveStory() || {};
        const ideationContext = this.workspace.getIdeationContext();

        const formValues = {
            request: promptText, model: this.dom.modelSelect.value, title: titleText,
            wordCount: this.dom.wordCount.value, tone: activeStory.masterTone || 'Thô mộc, tự nhiên, bộc trực',
            chapterToneOverride: this.dom.chapterToneOverride ? this.dom.chapterToneOverride.value.trim() : '',
            masterTone: activeStory.masterTone || '', masterOutline: activeStory.masterOutline || '',
            constraints: [
                ...(this.dom.constraints ? this.dom.constraints.value.split('\n').map(c => c.trim()).filter(Boolean) : []),
                ...(ideationContext ? [`Thông tin từ các phiên chat phát triển ý tưởng:\n${ideationContext}`] : [])
            ]
        };

        this.currentModel = formValues.model;
        this.dom.activeTitle.innerText = titleText;
        this.dom.activeModelBadge.innerText = formValues.model;

        this.dom.welcomeContainer.classList.add('hidden');
        this.dom.feedThread.classList.remove('hidden');
        this.dom.userPromptDisplay.innerText = promptText;
        this.setChapterContent('', false);
        this.updateWordCount();

        this.dom.progressContainer.classList.remove('hidden');
        this.dom.progressFill.style.width = '0%';
        this.dom.jobStep.innerText = 'Đang chuẩn bị...';
        this.dom.actionPanel.classList.add('hidden');
        this.dom.analysisResults.classList.add('hidden');
        this.dom.analysisIdle.classList.remove('hidden');
        this.dom.qualityScore.classList.add('hidden');
        this.dom.memoryResults.classList.add('hidden');
        this.dom.memoryIdle.classList.remove('hidden');

        this.dom.btnGenerate.disabled = true;
        this.service.startGeneration(
            storyId,
            formValues,
            (s) => { if (this.workspace.currentStoryId === storyId) this.updateStatusView(s); },
            (t) => { if (this.workspace.currentStoryId === storyId) this.appendTokenView(t); },
            (r) => this.handleGenerationComplete(r, storyId, titleText),
            (e) => this.handleGenerationError(e)
        );
    }

    async handleChatMessage(message) {
        const storyId = this.workspace.currentStoryId;
        const threadId = this.workspace.currentSubthreadId;
        const story = this.workspace.getActiveStory();
        const thread = this.workspace.getSubthread(threadId, storyId);
        if (!thread) return;
        const history = thread.messages.slice(-20);
        this.workspace.addSubthreadMessage(threadId, 'user', message, storyId);
        this.dom.userPrompt.value = '';
        this.dom.userPrompt.style.height = '';
        this.dom.userPrompt.style.overflowY = 'hidden';
        this.renderChatThread(thread, true);
        this.dom.btnGenerate.disabled = true;
        this.dom.sendText.innerText = 'Đang trả lời...';
        try {
            const reply = await this.service.chat(storyId, {
                message,
                model: this.dom.modelSelect.value,
                thread_id: threadId,
                thread_title: thread.title,
                history,
                master_outline: story.masterOutline || '',
                master_tone: story.masterTone || ''
            });
            this.workspace.addSubthreadMessage(threadId, 'assistant', reply, storyId);
            if (this.workspace.currentStoryId === storyId && this.workspace.currentSubthreadId === threadId) {
                this.renderChatThread(thread);
            }
        } catch (error) {
            if (this.workspace.currentStoryId === storyId && this.workspace.currentSubthreadId === threadId) {
                this.renderChatThread(thread);
            }
            alert(`Sự cố chat: ${error.message || error}`);
        } finally {
            this.dom.btnGenerate.disabled = false;
            if (this.workspace.currentSubthreadId) this.dom.sendText.innerText = 'Gửi tin nhắn';
        }
    }

    appendTokenView(token) {
        this.chapterSource += token;
        this.dom.streamOutput.innerText = this.chapterSource;
        this.updateWordCount();
    }

    updateStatusView(jobState) {
        const stepLabels = { 'PLANNING': 'Lập kế hoạch...', 'RETRIEVING': 'Truy vấn ký ức...', 'BUILDING_PROMPT': 'Dựng prompt...', 'GENERATING': 'Đang sinh nội dung...', 'ANALYZING': 'Phân tích chất lượng...' };
        this.dom.jobStep.innerText = stepLabels[jobState.current_step] || jobState.status;
        this.dom.progressFill.style.width = `${jobState.progress}%`;
    }

    handleGenerationComplete(result, storyId, title) {
        const content = result.content ?? this.dom.streamOutput.innerText;
        this.workspace.saveChapterToCurrentStory({
            chapterId: result.chapter_id,
            versionId: result.version_id,
            title,
            content,
            model: this.currentModel,
            status: result.status || 'DRAFT'
        }, storyId);
        this.dom.progressContainer.classList.add('hidden');
        this.dom.btnGenerate.disabled = false;
        if (this.workspace.currentStoryId !== storyId) return;

        this.workspace.currentChapterId = result.chapter_id;
        this.workspace.currentVersionId = result.version_id;
        this.setChapterContent(content);
        this.dom.actionPanel.classList.remove('hidden');
        this.updateWordCount();
        this.syncWorkspaceUI();
        if (result.analysis) StoryAnalysisRenderer.renderAnalysisResults(this.dom, result.analysis);
    }

    handleGenerationError(error) {
        this.dom.progressContainer.classList.add('hidden');
        this.dom.btnGenerate.disabled = false;
        alert(`Sự cố sinh chương: ${error.message || error}`);
    }

    async handleApprove() {
        if (!this.workspace.currentChapterId || !this.workspace.currentVersionId) return;
        try {
            this.dom.btnApprove.disabled = true;
            this.dom.memoryIdle.innerText = 'Đang trích xuất ký ức...';
            await this.service.approveChapter(this.workspace.currentStoryId, this.workspace.currentChapterId, this.workspace.currentVersionId);
            this.workspace.saveChapterToCurrentStory({
                chapterId: this.workspace.currentChapterId,
                status: 'APPROVED'
            });
            this.updateChapterStatus('APPROVED');
            this.dom.memoryIdle.classList.add('hidden');
            this.dom.memoryResults.classList.remove('hidden');
            this.dom.memSummary.textContent = 'Đã cập nhật ký ức dài hạn cho chương này.';
            this.dom.memFacts.replaceChildren();
            alert("✅ Đã duyệt chương và ghi nhận ký ức vào Vector DB!");
        } catch (e) { alert(`Lỗi: ${e.message}`); }
        finally { this.dom.btnApprove.disabled = false; }
    }

    async handleRegenerate() {
        const feedback = this.dom.feedbackInput.value.trim();
        if (!feedback) return alert("Vui lòng nhập phản hồi!");
        const storyId = this.workspace.currentStoryId;
        const title = this.dom.activeTitle.innerText;
        this.dom.welcomeContainer.classList.add('hidden');
        this.dom.feedThread.classList.remove('hidden');
        this.dom.userPromptDisplay.innerText = `[Tái tạo]: ${feedback}`;
        this.setChapterContent('', false);
        this.dom.progressContainer.classList.remove('hidden');
        this.dom.progressFill.style.width = '0%';
        this.dom.jobStep.innerText = 'Đang chuẩn bị tái tạo...';
        this.dom.actionPanel.classList.add('hidden');

        try {
            const result = await this.service.regenerateChapter(storyId, this.workspace.currentChapterId, this.workspace.currentVersionId, feedback, this.currentModel);
            this.handleGenerationComplete(result, storyId, title);
        } catch (error) { this.handleGenerationError(error); }
    }

    async handleContinue() {
        const feedback = this.dom.feedbackInput.value.trim() || 'Viết tiếp diễn biến tiếp theo';
        const storyId = this.workspace.currentStoryId;
        const title = this.dom.activeTitle.innerText;
        this.dom.userPromptDisplay.innerText = `[Viết tiếp]: ${feedback}`;
        this.setChapterContent('', false);
        this.dom.progressContainer.classList.remove('hidden');
        this.dom.progressFill.style.width = '0%';
        this.dom.jobStep.innerText = 'Đang chuẩn bị viết tiếp...';
        this.dom.actionPanel.classList.add('hidden');

        try {
            const result = await this.service.continueChapter(storyId, this.workspace.currentChapterId, feedback, this.currentModel || this.dom.modelSelect.value);
            this.handleGenerationComplete(result, storyId, title);
        } catch (error) { this.handleGenerationError(error); }
    }

    async handleAnalyze() {
        if (!this.workspace.currentChapterId || !this.workspace.currentVersionId) return;
        try {
            this.dom.btnAnalyze.disabled = true;
            this.dom.analysisIdle.innerText = 'Đang phân tích...';
            this.dom.analysisIdle.classList.remove('hidden');
            this.dom.analysisResults.classList.add('hidden');
            const analysis = await this.service.analyzeChapter(this.workspace.currentStoryId, this.workspace.currentChapterId, this.workspace.currentVersionId);
            StoryAnalysisRenderer.renderAnalysisResults(this.dom, analysis);
        } catch (e) { alert(`Lỗi phân tích: ${e.message}`); }
        finally { this.dom.btnAnalyze.disabled = false; }
    }

    async handleCancelJob() {
        if (this.service.currentJobId) {
            try { await this.service.cancelJob(this.service.currentJobId); alert("Đã gửi yêu cầu hủy."); }
            catch (e) { alert(`Lỗi: ${e.message}`); }
        }
    }
}
