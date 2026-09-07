const assert = require('node:assert/strict');
const path = require('node:path');
const AuthController = require('../static/authController.js');

// Mock localStorage and sessionStorage for testing
class MockStorage {
    constructor() {
        this.store = new Map();
    }
    getItem(key) {
        return this.store.has(key) ? this.store.get(key) : null;
    }
    setItem(key, value) {
        this.store.set(key, String(value));
    }
    removeItem(key) {
        this.store.delete(key);
    }
    clear() {
        this.store.clear();
    }
}

global.localStorage = new MockStorage();
global.sessionStorage = new MockStorage();

function runContractTests() {
    console.log('--- Running Auth Contract Tests ---');

    // 1. Validation Tests
    const controller = new AuthController();

    // 1.1 Email Validation
    assert.equal(controller.validateEmail('tacgia@example.com'), true, 'Valid standard email should pass');
    assert.equal(controller.validateEmail('user.name+tag@sub.domain.vn'), true, 'Email with subdomains and tags should pass');
    assert.equal(controller.validateEmail(''), false, 'Empty email should fail');
    assert.equal(controller.validateEmail('invalid-email'), false, 'Email without @ should fail');
    assert.equal(controller.validateEmail('user@'), false, 'Email without domain should fail');
    assert.equal(controller.validateEmail('@domain.com'), false, 'Email without username should fail');
    assert.equal(controller.validateEmail('user@domain'), false, 'Email without TLD should fail');
    console.log('✓ Email validation tests passed');

    // 1.2 Password Requirements (>= 8 chars, 1 uppercase, 1 number)
    assert.equal(controller.validatePasswordRequirements('Password123'), true, 'Valid strong password should pass');
    assert.equal(controller.validatePasswordRequirements('MatKhau1'), true, '8 chars with upper and number should pass');
    assert.equal(controller.validatePasswordRequirements('pass1234'), false, 'Missing uppercase should fail');
    assert.equal(controller.validatePasswordRequirements('PASSWORD!'), false, 'Missing number should fail');
    assert.equal(controller.validatePasswordRequirements('Pass1'), false, 'Less than 8 chars should fail');
    assert.equal(controller.validatePasswordRequirements(''), false, 'Empty password should fail');
    console.log('✓ Password requirement tests passed');

    // 1.3 Initials Generation for User Avatar
    assert.equal(controller.getInitials('Thanh Phong'), 'TP', 'Should extract first and last initials');
    assert.equal(controller.getInitials('Nguyễn Văn A'), 'NA', 'Should extract first and last initials of multi-word names');
    assert.equal(controller.getInitials('Author'), 'AU', 'Single word name should take first two letters');
    assert.equal(controller.getInitials(''), 'TG', 'Empty string should return fallback TG');
    console.log('✓ Initials generation tests passed');

    // 2. Auth State & Session Storage Tests
    global.localStorage.clear();
    global.sessionStorage.clear();

    const auth = new AuthController({
        storageKey: 'test_auth_user',
        pendingActionKey: 'test_pending_action'
    });

    assert.equal(auth.isAuthenticated(), false, 'Initial state should be unauthenticated');
    assert.equal(auth.getCurrentUser(), null, 'Initial user should be null');

    // Save User (Login)
    const testUser = {
        id: 'user_123',
        displayName: 'Nguyễn Du',
        email: 'nguyendu@example.com',
        tier: 'Tác giả'
    };
    auth.saveUser(testUser, true);

    assert.equal(auth.isAuthenticated(), true, 'Should be authenticated after saveUser');
    assert.equal(auth.getCurrentUser().displayName, 'Nguyễn Du');
    assert.equal(auth.getCurrentUser().email, 'nguyendu@example.com');
    console.log('✓ User session storage and authentication state tests passed');

    // Logout
    auth.handleLogout();
    assert.equal(auth.isAuthenticated(), false, 'Should be unauthenticated after logout');
    assert.equal(auth.getCurrentUser(), null, 'User should be null after logout');
    console.log('✓ Logout tests passed');

    // 3. Pending Action Preservation (Composer / Story Creation)
    const pendingData = {
        type: 'SUBMIT_PROMPT',
        prompt: 'Đêm nay trăng thanh gió mát trên đỉnh núi Ba Vì...'
    };
    auth.setPendingAction(pendingData);
    assert.deepEqual(auth.loadPendingAction(), pendingData, 'Pending action should be saved in storage');

    let callbackFired = false;
    let receivedAction = null;
    auth.onAuthSuccessCallback = ({ user, action }) => {
        callbackFired = true;
        receivedAction = action;
    };

    auth.finishAuthSuccess(testUser);
    assert.equal(callbackFired, true, 'finishAuthSuccess should trigger callback');
    assert.deepEqual(receivedAction, pendingData, 'Pending action should be passed to callback');
    assert.equal(auth.loadPendingAction(), null, 'Pending action should be cleared after consumption');
    console.log('✓ Pending action preservation & resume tests passed');

    console.log('All auth contract checks passed successfully!');
}

runContractTests();
