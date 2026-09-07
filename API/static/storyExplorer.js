const StoryExplorer = {
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
