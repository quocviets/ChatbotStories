/**
 * STORY WORKSPACE (Model & State Manager Layer)
 * Manages Multi-Story persistence, Sub-Chat Threads, and Sidebar Story Cards rendering.
 */
class StoryWorkspace {
    constructor() {
        this.stories = [];
        this.currentStoryId = null;
        this.currentSubthreadId = null;
        this.currentChapterId = null;
        this.currentVersionId = null;
        this.recentChapterLimit = 15;
    }

    readLegacyStories() {
        const raw = localStorage.getItem('ai_story_workspace');
        if (!raw) return [];
        try {
            const stories = JSON.parse(raw);
            if (!Array.isArray(stories)) return [];
            return stories
                .filter(story => story?.id && story?.title)
                .map(story => ({
                    id: story.id,
                    title: story.title,
                    masterTone: story.masterTone || '',
                    masterOutline: story.masterOutline || '',
                    createdAt: story.createdAt || null,
                    archivedAt: story.archivedAt || null
                }));
        } catch (error) {
            return [];
        }
    }

    clearLegacyStories() {
        localStorage.removeItem('ai_story_workspace');
    }

    init(stories = []) {
        this.stories = stories.map(story => ({
            ...story,
            chapters: story.chapters || [],
            subthreads: story.subthreads || [],
            deletedChapterSources: story.deletedChapterSources || []
        }));
        if (!this.stories.length) return null;
        const firstActiveStory = this.stories.find(story => !story.archivedAt) || this.stories[0];
        return this.selectStory(firstActiveStory.id);
    }

    saveState() {
        // PostgreSQL is the only persistence layer for story domain data.
    }

    getActiveStory() {
        return this.stories.find(s => s.id === this.currentStoryId) || null;
    }

    getActiveStories() {
        return this.stories.filter(story => !story.archivedAt);
    }

    getArchivedStories() {
        return this.stories.filter(story => story.archivedAt);
    }

    getMode() {
        if (this.currentSubthreadId) return 'chat';
        if (this.currentChapterId) return 'chapter';
        return 'new-chapter';
    }

    createStory(story) {
        const newStory = {
            ...story,
            chapters: [],
            subthreads: [],
            deletedChapterSources: []
        };
        this.stories.unshift(newStory);
        this.saveState();
        this.selectStory(newStory.id);
        return newStory;
    }

    selectStory(storyId) {
        const found = this.stories.find(s => s.id === storyId && !s.archivedAt);
        if (!found) return null;
        this.currentStoryId = found.id;
        this.currentSubthreadId = null;
        this.currentChapterId = null;
        this.currentVersionId = null;
        return found;
    }

    archiveStory(storyId) {
        const story = this.stories.find(item => item.id === storyId && !item.archivedAt);
        if (!story || this.getActiveStories().length <= 1) return false;
        story.archivedAt = new Date().toISOString();
        if (this.currentStoryId === storyId) {
            this.selectStory(this.getActiveStories()[0].id);
        }
        this.saveState();
        return true;
    }

    restoreStory(storyId) {
        const story = this.stories.find(item => item.id === storyId && item.archivedAt);
        if (!story) return false;
        delete story.archivedAt;
        this.saveState();
        return true;
    }

    createSubthread(title) {
        const activeStory = this.getActiveStory();
        if (!activeStory) return null;
        if (!activeStory.subthreads) activeStory.subthreads = [];

        const subthread = {
            id: crypto.randomUUID(),
            title: title || `Chat ${activeStory.subthreads.length + 1}`,
            createdAt: new Date().toISOString(),
            messages: []
        };
        activeStory.subthreads.unshift(subthread);
        this.saveState();
        this.currentSubthreadId = subthread.id;
        return subthread;
    }

    selectSubthread(threadId) {
        const activeStory = this.getActiveStory();
        if (!activeStory || !activeStory.subthreads) return null;
        const found = activeStory.subthreads.find(t => t.id === threadId);
        if (!found) return null;
        this.currentSubthreadId = found.id;
        this.currentChapterId = null;
        this.currentVersionId = null;
        return found;
    }

    getSubthread(threadId = this.currentSubthreadId, storyId = this.currentStoryId) {
        return this.stories.find(story => story.id === storyId)?.subthreads?.find(thread => thread.id === threadId) || null;
    }

    addSubthreadMessage(threadId, role, content, storyId = this.currentStoryId, metadata = {}) {
        const thread = this.getSubthread(threadId, storyId);
        if (!thread) return;
        thread.messages.push({ role, content, ...metadata });
        this.saveState();
    }

    replaceSubthreads(storyId, subthreads) {
        const story = this.stories.find(item => item.id === storyId);
        if (!story) return;
        const localThreads = story.subthreads || [];
        story.subthreads = subthreads.map(thread => {
            const local = localThreads.find(item => item.id === thread.id);
            return {
                ...local,
                ...thread,
                messages: thread.messages.map((message, index) => ({
                    ...local?.messages?.[index],
                    ...message,
                })),
            };
        });
        this.reconcileChapterLinks(storyId);
        this.saveState();
    }

    replaceChapters(storyId, chapters, deletedSources = []) {
        const story = this.stories.find(item => item.id === storyId);
        if (!story) return;
        story.chapters = chapters;
        story.deletedChapterSources = deletedSources;
        this.reconcileChapterLinks(storyId);
    }

    reconcileChapterLinks(storyId = this.currentStoryId) {
        const story = this.stories.find(item => item.id === storyId);
        if (!story) return;
        (story.chapters || []).forEach(chapter => {
            const thread = story.subthreads?.find(item => item.id === chapter.sourceThreadId);
            const message = thread?.messages?.[Number(chapter.sourceMessageIndex)];
            if (!message || message.role !== 'assistant') return;
            Object.assign(message, {
                kind: 'chapter-draft',
                chapterId: chapter.chapterId,
                versionId: chapter.versionId,
                title: chapter.title,
                model: chapter.model,
                status: chapter.status
            });
        });
        (story.deletedChapterSources || []).forEach(source => {
            const thread = story.subthreads?.find(item => item.id === source.sourceThreadId);
            const message = thread?.messages?.[Number(source.sourceMessageIndex)];
            if (!message || message.role !== 'assistant') return;
            Object.assign(message, {
                kind: 'chapter-draft',
                chapterId: source.chapterId,
                status: 'DELETED',
                chapterDeleted: true
            });
            delete message.versionId;
        });
    }

    deleteSubthread(threadId) {
        const activeStory = this.getActiveStory();
        if (!activeStory) return false;
        const originalLength = activeStory.subthreads.length;
        activeStory.subthreads = activeStory.subthreads.filter(thread => thread.id !== threadId);
        if (activeStory.subthreads.length === originalLength) return false;
        if (this.currentSubthreadId === threadId) this.currentSubthreadId = null;
        this.saveState();
        return true;
    }

    getThreadContext(threadId = this.currentSubthreadId, maxChars = 8000) {
        const messages = this.getSubthread(threadId)?.messages || [];
        return messages.slice(-20).map(message =>
            `${message.role === 'user' ? 'Người dùng' : 'Trợ lý'}: ${message.content}`
        ).join('\n').slice(-maxChars);
    }

    saveChapterToCurrentStory(chapterData, storyId = this.currentStoryId) {
        const activeStory = this.stories.find(story => story.id === storyId);
        if (!activeStory) return;
        if (!activeStory.chapters) activeStory.chapters = [];

        const existingIdx = activeStory.chapters.findIndex(c => c.chapterId === chapterData.chapterId);
        if (existingIdx >= 0) {
            activeStory.chapters[existingIdx] = { ...activeStory.chapters[existingIdx], ...chapterData };
        } else {
            activeStory.chapters.unshift(chapterData);
        }
        this.saveState();
    }

    deleteChapter(chapterId) {
        const activeStory = this.getActiveStory();
        if (!activeStory) return false;
        const originalLength = activeStory.chapters.length;
        activeStory.chapters = activeStory.chapters.filter(chapter => chapter.chapterId !== chapterId);

        if (activeStory.subthreads) {
            activeStory.subthreads.forEach(thread => {
                if (thread.messages) {
                    thread.messages.forEach(msg => {
                        if (msg.chapterId === chapterId) {
                            delete msg.versionId;
                            msg.status = 'DELETED';
                            msg.chapterDeleted = true;
                            delete msg.superseded;
                        }
                    });
                }
            });
        }

        if (this.currentChapterId === chapterId) {
            this.currentChapterId = null;
            this.currentVersionId = null;
        }
        this.saveState();
        return true;
    }

    renameChapter(chapterId, title) {
        const chapter = this.getActiveStory()?.chapters?.find(item => item.chapterId === chapterId);
        if (!chapter || !title.trim()) return false;
        chapter.title = title.trim();
        this.saveState();
        return true;
    }

    getChapters({ query = '', oldestFirst = false, limit } = {}) {
        const normalizedQuery = query.trim().toLocaleLowerCase('vi');
        let chapters = [...(this.getActiveStory()?.chapters || [])];
        if (normalizedQuery) {
            chapters = chapters.filter(chapter =>
                (chapter.title || '').toLocaleLowerCase('vi').includes(normalizedQuery)
            );
        }
        if (oldestFirst) chapters.reverse();
        return limit ? chapters.slice(0, limit) : chapters;
    }

    getAdjacentChapter(chapterId, offset) {
        const chapters = this.getChapters({ oldestFirst: true });
        const index = chapters.findIndex(chapter => chapter.chapterId === chapterId);
        return index < 0 ? null : chapters[index + offset] || null;
    }

    renderStoriesList(container, onSelect, onArchive) {
        if (!container) return;
        container.innerHTML = '';
        this.getActiveStories().forEach(s => {
            const card = document.createElement('div');
            card.className = `story-card ${s.id === this.currentStoryId ? 'active' : ''}`;
            
            const title = document.createElement('div');
            title.className = 'story-title';
            title.innerText = s.title;
            
            const badge = document.createElement('div');
            badge.className = 'story-badge';
            badge.innerText = `${s.chapters?.length || s.chapterCount || 0} chương`;

            const archiveButton = document.createElement('button');
            archiveButton.type = 'button';
            archiveButton.className = 'story-archive-action';
            archiveButton.textContent = '📦';
            archiveButton.title = `Lưu trữ ${s.title}`;
            archiveButton.setAttribute('aria-label', `Lưu trữ ${s.title}`);
            archiveButton.addEventListener('click', event => {
                event.stopPropagation();
                onArchive(s.id, s.title);
            });

            card.append(title, badge, archiveButton);
            card.addEventListener('click', () => onSelect(s.id));
            container.appendChild(card);
        });
    }

    renderArchivedStoriesList(container, onRestore) {
        if (!container) return;
        container.replaceChildren();
        const stories = this.getArchivedStories();
        if (!stories.length) {
            const empty = document.createElement('p');
            empty.className = 'story-tool-empty';
            empty.textContent = 'Chưa có bộ truyện nào được lưu trữ.';
            container.appendChild(empty);
            return;
        }
        stories.forEach(story => {
            const item = document.createElement('div');
            item.className = 'archived-story-item';
            const info = document.createElement('div');
            const title = document.createElement('strong');
            title.textContent = story.title;
            const meta = document.createElement('small');
            meta.textContent = `${story.chapters?.length || story.chapterCount || 0} chương · ${story.subthreads?.length || story.chatCount || 0} phiên chat`;
            info.append(title, meta);
            const restoreButton = document.createElement('button');
            restoreButton.type = 'button';
            restoreButton.textContent = 'Khôi phục';
            restoreButton.addEventListener('click', () => onRestore(story.id));
            item.append(info, restoreButton);
            container.appendChild(item);
        });
    }

    renderSubthreadsList(container, onSelect, onDelete) {
        if (!container) return;
        container.innerHTML = '';
        const activeStory = this.getActiveStory();
        if (!activeStory || !activeStory.subthreads || activeStory.subthreads.length === 0) {
            container.innerHTML = '<div class="info-placeholder">Chưa có phiên chat thử nghiệm nào.</div>';
            return;
        }

        activeStory.subthreads.forEach(st => {
            const item = document.createElement('div');
            item.className = `history-item ${st.id === this.currentSubthreadId ? 'active' : ''}`;
            const icon = document.createElement('span');
            icon.className = 'item-icon';
            icon.textContent = '💬';
            const title = document.createElement('span');
            title.className = 'item-title';
            title.textContent = st.title;
            const deleteButton = document.createElement('button');
            deleteButton.type = 'button';
            deleteButton.className = 'history-delete';
            deleteButton.textContent = '×';
            deleteButton.title = `Xóa chat ${st.title}`;
            deleteButton.setAttribute('aria-label', `Xóa chat ${st.title}`);
            deleteButton.addEventListener('click', event => {
                event.stopPropagation();
                onDelete(st.id, st.title);
            });
            item.append(icon, title, deleteButton);
            item.addEventListener('click', () => onSelect(st.id));
            container.appendChild(item);
        });
    }

    renderChaptersList(container, onSelect, onDelete, onRename, chapters = this.getChapters(), emptyText = 'Chưa có chương nào trong bộ truyện này.') {
        if (!container) return;
        container.innerHTML = '';
        if (chapters.length === 0) {
            container.innerHTML = `<div class="info-placeholder">${emptyText}</div>`;
            return;
        }

        chapters.forEach((chap, idx) => {
            const item = document.createElement('div');
            item.className = `history-item ${chap.chapterId === this.currentChapterId ? 'active' : ''}`;
            const icon = document.createElement('span');
            icon.className = 'item-icon';
            icon.textContent = '📖';
            const title = document.createElement('span');
            title.className = 'item-title';
            title.textContent = chap.title || `Chương ${idx + 1}`;
            const renameButton = document.createElement('button');
            renameButton.type = 'button';
            renameButton.className = 'history-rename';
            renameButton.textContent = '✎';
            renameButton.title = `Đổi tên ${title.textContent}`;
            renameButton.setAttribute('aria-label', `Đổi tên ${title.textContent}`);
            renameButton.addEventListener('click', event => {
                event.stopPropagation();
                const input = document.createElement('input');
                input.className = 'history-rename-input';
                input.value = title.textContent;
                title.replaceWith(input);
                input.focus();
                input.select();
                let finished = false;
                const finish = save => {
                    if (finished) return;
                    finished = true;
                    const nextTitle = input.value.trim();
                    if (save && nextTitle && nextTitle !== title.textContent) onRename(chap, nextTitle);
                    else input.replaceWith(title);
                };
                input.addEventListener('keydown', keyEvent => {
                    if (keyEvent.key === 'Enter') finish(true);
                    if (keyEvent.key === 'Escape') finish(false);
                });
                input.addEventListener('blur', () => finish(true), { once: true });
            });
            const deleteButton = document.createElement('button');
            deleteButton.type = 'button';
            deleteButton.className = 'history-delete';
            deleteButton.textContent = '×';
            deleteButton.title = `Xóa ${title.textContent}`;
            deleteButton.setAttribute('aria-label', `Xóa ${title.textContent}`);
            deleteButton.addEventListener('click', event => {
                event.stopPropagation();
                onDelete(chap);
            });
            item.append(icon, title, renameButton, deleteButton);
            item.addEventListener('click', () => onSelect(chap));
            container.appendChild(item);
        });
    }
}
