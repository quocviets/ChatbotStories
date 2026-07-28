const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

let storedWorkspace = '';
const context = {
    console,
    crypto: { randomUUID: () => 'generated-id' },
    localStorage: {
        getItem: () => null,
        setItem: (key, value) => { if (key === 'ai_story_workspace') storedWorkspace = value; }
    }
};
vm.createContext(context);

vm.runInContext(`${fs.readFileSync('static/storyService.js', 'utf8')}\nglobalThis.StoryService = StoryService;`, context);
vm.runInContext(`${fs.readFileSync('static/storyWorkspace.js', 'utf8')}\nglobalThis.StoryWorkspace = StoryWorkspace;`, context);
vm.runInContext(`${fs.readFileSync('static/storyRepository.js', 'utf8')}\nglobalThis.StoryRepository = StoryRepository;`, context);
vm.runInContext(`${fs.readFileSync('static/storyController.js', 'utf8')}\nglobalThis.StoryController = StoryController;`, context);

assert.deepEqual(
    Array.from(context.StoryController.splitBoldText('1. **Ý tưởng cốt lõi:** Nội dung')),
    ['1. ', '**Ý tưởng cốt lõi:**', ' Nội dung']
);
assert.deepEqual(
    Array.from(context.StoryController.splitBoldText('Dấu ** chưa đóng')),
    ['Dấu ** chưa đóng']
);

const completedController = new context.StoryController({});
let progressHidden = false;
completedController.workspace = {
    currentStoryId: 'story-b',
    saveChapterToCurrentStory: () => {}
};
completedController.dom = {
    streamOutput: { innerText: '' },
    progressContainer: { classList: { add: value => { progressHidden = value === 'hidden'; } } },
    btnGenerate: { disabled: true }
};
completedController.handleGenerationComplete({
    chapter_id: 'chapter-a',
    version_id: 'version-a',
    content: 'done'
}, 'story-a', 'Chapter A');
assert.equal(progressHidden, true);
assert.equal(completedController.dom.btnGenerate.disabled, false);

for (const method of ['chat', 'loadChats', 'saveChatThread', 'deleteChatThread', 'getChapter', 'deleteChapter', 'renameChapter', 'exportChatChapter', 'approveChapter', 'regenerateChapter', 'continueChapter', 'analyzeChapter']) {
    assert.equal(typeof context.StoryService.prototype[method], 'function', `${method} is missing`);
}
assert.equal(typeof context.StoryRepository.prototype.chat, 'function', 'repository.chat is missing');
assert.equal(typeof context.StoryRepository.prototype.getChatThreads, 'function', 'repository.getChatThreads is missing');
assert.equal(typeof context.StoryRepository.prototype.saveChatThread, 'function', 'repository.saveChatThread is missing');
assert.equal(typeof context.StoryRepository.prototype.deleteChatThread, 'function', 'repository.deleteChatThread is missing');
assert.equal(typeof context.StoryRepository.prototype.deleteChapter, 'function', 'repository.deleteChapter is missing');
assert.equal(typeof context.StoryRepository.prototype.renameChapter, 'function', 'repository.renameChapter is missing');
assert.equal(typeof context.StoryRepository.prototype.getChapter, 'function', 'repository.getChapter is missing');
assert.equal(typeof context.StoryRepository.prototype.exportChatChapter, 'function', 'repository.exportChatChapter is missing');
assert.equal(typeof context.StoryController.prototype.exportChatMessageAsChapter, 'function', 'exportChatMessageAsChapter is missing');

const workspace = new context.StoryWorkspace();
workspace.stories = [
    { id: 'story-a', chapters: [] },
    { id: 'story-b', chapters: [] }
];
workspace.currentStoryId = 'story-b';
workspace.currentSubthreadId = 'chat-b';
assert.equal(workspace.getMode(), 'chat');
workspace.currentSubthreadId = null;
workspace.currentChapterId = 'chapter-b';
assert.equal(workspace.getMode(), 'chapter');
workspace.currentChapterId = null;
assert.equal(workspace.getMode(), 'new-chapter');
workspace.saveChapterToCurrentStory({ chapterId: 'chapter-a' }, 'story-a');
assert.equal(workspace.stories[0].chapters[0].chapterId, 'chapter-a');
assert.equal(workspace.stories[1].chapters.length, 0);
workspace.currentStoryId = 'story-a';
assert.equal(workspace.deleteChapter('chapter-a'), true);
assert.equal(workspace.stories[0].chapters.length, 0);

workspace.stories[0].chapters = Array.from({ length: 45 }, (_, index) => ({
    chapterId: `chapter-${45 - index}`,
    title: `Chương ${45 - index}`,
    content: `Nội dung ${45 - index}`
}));
assert.deepEqual(
    Array.from(workspace.getChapters({ limit: 15 }), chapter => chapter.chapterId),
    Array.from({ length: 15 }, (_, index) => `chapter-${45 - index}`)
);
assert.equal(workspace.getChapters({ oldestFirst: true })[0].chapterId, 'chapter-1');
assert.equal(workspace.getChapters({ query: 'chương 22' })[0].chapterId, 'chapter-22');
assert.equal(workspace.getAdjacentChapter('chapter-20', -1).chapterId, 'chapter-19');
assert.equal(workspace.getAdjacentChapter('chapter-20', 1).chapterId, 'chapter-21');
workspace.saveState();
const persistedChapters = JSON.parse(storedWorkspace)[0].chapters;
assert.equal(persistedChapters[0].content, 'Nội dung 45');
assert.equal('content' in persistedChapters[15], false);

workspace.stories[0].subthreads = [{ id: 'chat-a', title: 'Ý tưởng', messages: [] }];
workspace.currentStoryId = 'story-a';
workspace.addSubthreadMessage('chat-a', 'user', 'Nhân vật phản diện là người cố vấn.');
assert.match(workspace.getIdeationContext(), /Nhân vật phản diện/);
workspace.replaceSubthreads('story-a', [{ id: 'chat-db', title: 'Đã lưu', messages: [] }]);
assert.equal(workspace.getSubthread('chat-db', 'story-a').title, 'Đã lưu');
workspace.currentSubthreadId = 'chat-db';
assert.equal(workspace.deleteSubthread('chat-db'), true);
assert.equal(workspace.getIdeationContext(), '');
workspace.stories[0].chapters = [{ chapterId: 'chapter-title', title: 'Tên cũ' }];
assert.equal(workspace.renameChapter('chapter-title', 'Tên mới'), true);
assert.equal(workspace.stories[0].chapters[0].title, 'Tên mới');

const archiveWorkspace = new context.StoryWorkspace();
archiveWorkspace.stories = [
    { id: 'story-active', title: 'Đang viết', chapters: [], subthreads: [] },
    { id: 'story-old', title: 'Truyện cũ', chapters: [{ chapterId: 'chapter-old' }], subthreads: [{ id: 'chat-old' }] }
];
archiveWorkspace.currentStoryId = 'story-old';
assert.equal(archiveWorkspace.archiveStory('story-old'), true);
assert.equal(archiveWorkspace.currentStoryId, 'story-active');
assert.equal(archiveWorkspace.getActiveStories().length, 1);
assert.equal(archiveWorkspace.getArchivedStories()[0].chapters[0].chapterId, 'chapter-old');
assert.equal(archiveWorkspace.restoreStory('story-old'), true);
assert.equal(archiveWorkspace.getActiveStories().length, 2);
assert.equal(archiveWorkspace.archiveStory('missing-story'), false);

(async () => {
    let capturedRequest;
    context.fetch = async (url, options) => {
        capturedRequest = { url, options };
        return { ok: true, json: async () => ({ data: { reply: 'ok' } }) };
    };
    const repository = new context.StoryRepository();
    await repository.chat('story-a', { message: 'hello' });
    assert.equal(capturedRequest.options.method, 'POST');
    assert.equal(capturedRequest.options.headers['Content-Type'], 'application/json');
    assert.equal(capturedRequest.options.body, '{"message":"hello"}');

    context.fetch = async () => ({
        ok: false,
        statusText: 'Unprocessable Entity',
        json: async () => ({
            detail: [{ loc: ['body', 'request'], msg: 'String should have at least 5 characters' }]
        })
    });
    await assert.rejects(repository.generateChapter('story-a', {}), error => {
        assert.equal(error.message, 'request: String should have at least 5 characters');
        assert.equal(error.message.includes('[object Object]'), false);
        return true;
    });
    console.log('story contract checks passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
