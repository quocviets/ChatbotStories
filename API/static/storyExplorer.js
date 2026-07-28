const StoryExplorer = {
    renderMindmap(container, story, onChapterClick) {
        container.replaceChildren();

        const root = document.createElement('div');
        root.className = 'mindmap-root';
        root.textContent = story.title;
        container.appendChild(root);

        const branches = document.createElement('div');
        branches.className = 'mindmap-branches';
        container.appendChild(branches);

        if (!story.chapters?.length) {
            branches.innerHTML = '<p class="story-tool-empty">Chưa có chương nào để hiển thị.</p>';
            return;
        }

        story.chapters.forEach((chapter, index) => {
            const node = document.createElement('button');
            node.type = 'button';
            node.className = 'mindmap-node';

            const title = document.createElement('strong');
            title.textContent = chapter.title || `Chương ${index + 1}`;
            const words = (chapter.content || '').trim().split(/\s+/).filter(Boolean).length;
            const meta = document.createElement('small');
            meta.textContent = `Chương ${index + 1} · ${words} từ`;

            node.append(title, meta);
            node.addEventListener('click', () => onChapterClick(chapter));
            branches.appendChild(node);
        });
    },

    renderLoreResults(container, memories) {
        container.replaceChildren();
        if (!memories.length) {
            container.innerHTML = '<p class="story-tool-empty">Không tìm thấy lore phù hợp.</p>';
            return;
        }

        const labels = {
            SUMMARY: 'Tóm tắt',
            NEW_FACT: 'Sự kiện',
            CHARACTER_STATE: 'Nhân vật'
        };

        memories.forEach(memory => {
            const item = document.createElement('article');
            item.className = 'lore-result';

            const header = document.createElement('div');
            header.className = 'lore-result-header';
            const type = document.createElement('span');
            type.className = 'lore-type';
            type.textContent = labels[memory.type] || memory.type;
            header.appendChild(type);

            if (memory.similarity !== null) {
                const score = document.createElement('span');
                score.className = 'lore-score';
                score.textContent = `${Math.round(memory.similarity * 100)}% phù hợp`;
                header.appendChild(score);
            }

            const content = document.createElement('p');
            content.textContent = memory.content;
            item.append(header, content);
            container.appendChild(item);
        });
    }
};
