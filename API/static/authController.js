/**
 * AUTH CONTROLLER (AI Story Engine v3.0)
 * 100% Vanilla JavaScript - No external dependencies.
 * Responsibilities:
 * - Manages authentication state (unauthenticated, authenticated, pending action).
 * - Controls Auth Modal (<dialog id="auth-dialog">) for Login, Register, and Forgot Password.
 * - Handles Client-side real-time validation & accessibility (ARIA, focus management, trap focus).
 * - Preserves pending author action (Composer text, Create Story trigger) across auth flow.
 * - Manages the Upward Account Popover Menu in sidebar footer.
 */

class AuthController {
    constructor(options = {}) {
        this.storageKey = options.storageKey || 'ai_story_auth_user';
        this.pendingActionKey = options.pendingActionKey || 'ai_story_pending_action';
        this.currentUser = this.loadUser();
        this.pendingAction = this.loadPendingAction();
        this.activeTab = 'login'; // 'login' | 'register' | 'forgot' | 'forgot-success'
        this.resendCountdownInterval = null;
        this.resendSecondsLeft = 60;
        this.triggerElement = null;
        this.onAuthSuccessCallback = options.onAuthSuccess || null;
    }

    loadUser() {
        try {
            if (typeof localStorage === 'undefined') return null;
            const raw = localStorage.getItem(this.storageKey) || sessionStorage.getItem(this.storageKey);
            return raw ? JSON.parse(raw) : null;
        } catch {
            return null;
        }
    }

    saveUser(user, remember = true) {
        this.currentUser = user;
        try {
            if (typeof localStorage === 'undefined') return;
            const data = JSON.stringify(user);
            if (remember) {
                localStorage.setItem(this.storageKey, data);
            } else {
                sessionStorage.setItem(this.storageKey, data);
            }
        } catch (e) {
            console.warn('Không thể lưu phiên người dùng vào storage:', e);
        }
    }

    clearUser() {
        this.currentUser = null;
        try {
            if (typeof localStorage === 'undefined') return;
            localStorage.removeItem(this.storageKey);
            sessionStorage.removeItem(this.storageKey);
        } catch (e) {
            console.warn('Không thể xóa phiên người dùng:', e);
        }
    }

    loadPendingAction() {
        try {
            if (typeof sessionStorage === 'undefined') return null;
            const raw = sessionStorage.getItem(this.pendingActionKey);
            return raw ? JSON.parse(raw) : null;
        } catch {
            return null;
        }
    }

    setPendingAction(action) {
        this.pendingAction = action;
        try {
            if (typeof sessionStorage === 'undefined') return;
            if (action) {
                sessionStorage.setItem(this.pendingActionKey, JSON.stringify(action));
            } else {
                sessionStorage.removeItem(this.pendingActionKey);
            }
        } catch (e) {
            console.warn('Không thể lưu pending action:', e);
        }
    }

    isAuthenticated() {
        return !!this.currentUser;
    }

    getCurrentUser() {
        return this.currentUser;
    }

    init() {
        this.bindDOM();
        this.bindEvents();
        this.syncSidebarUI();
        this.checkServerSession();
    }

    async checkServerSession() {
        if (typeof window === 'undefined' || typeof fetch === 'undefined') return;

        // Check for Google OAuth error in URL query
        const params = new URLSearchParams(window.location.search);
        if (params.get('auth_error')) {
            const err = params.get('auth_error');
            const msg = err === 'google_denied'
                ? 'Bạn đã hủy yêu cầu xác thực bằng Google.'
                : 'Xác thực bằng tài khoản Google không thành công. Vui lòng thử lại.';
            this.openAuthModal('login');
            this.showGlobalAlert(msg, 'error');
            window.history.replaceState({}, document.title, window.location.pathname);
        }

        try {
            const res = await fetch('/api/v1/auth/me', { credentials: 'same-origin' });
            if (res.ok) {
                const json = await res.json();
                if (json && json.data && json.data.user) {
                    const user = {
                        id: json.data.user.id,
                        displayName: json.data.user.display_name,
                        email: json.data.user.email,
                        avatar: json.data.user.avatar_url,
                        tier: json.data.user.tier === 'author' ? 'Tác giả' : json.data.user.tier
                    };
                    this.saveUser(user, true);
                    this.syncSidebarUI();

                    // Check if returning from Google with a pending action
                    const pending = this.loadPendingAction();
                    if (pending) {
                        this.finishAuthSuccess(user);
                    }
                }
            } else if (res.status === 401) {
                if (this.currentUser) {
                    this.clearUser();
                    this.syncSidebarUI();
                }
            }
        } catch (e) {
            console.debug('Session check bypassed:', e);
        }
    }

    bindDOM() {
        if (typeof document === 'undefined') return;
        const get = id => document.getElementById(id);
        this.dom = {
            // Dialog & containers
            dialog: get('auth-dialog'),
            panel: get('auth-dialog-panel'),
            btnCloseDialog: get('btn-close-auth-dialog'),
            dialogEyebrow: get('auth-dialog-eyebrow'),
            dialogTitle: get('auth-dialog-title'),
            dialogDesc: get('auth-dialog-desc'),
            globalAlert: get('auth-global-alert'),

            // Tabs
            tabsContainer: get('auth-tabs'),
            tabLogin: get('tab-auth-login'),
            tabRegister: get('tab-auth-register'),

            // Section containers
            sectionOAuth: get('auth-section-oauth'),
            sectionDivider: get('auth-section-divider'),
            sectionLogin: get('auth-section-login'),
            sectionRegister: get('auth-section-register'),
            sectionForgot: get('auth-section-forgot'),
            sectionForgotSuccess: get('auth-section-forgot-success'),

            // OAuth
            btnGoogle: get('btn-auth-google'),
            googleBtnText: get('btn-auth-google-text'),
            googleSpinner: get('btn-auth-google-spinner'),

            // Login form
            formLogin: get('form-auth-login'),
            loginEmail: get('auth-login-email'),
            loginPassword: get('auth-login-password'),
            loginPasswordToggle: get('auth-login-password-toggle'),
            loginRemember: get('auth-login-remember'),
            btnLoginSubmit: get('btn-auth-login-submit'),
            btnLoginText: get('btn-auth-login-text'),
            btnLoginSpinner: get('btn-auth-login-spinner'),
            linkForgotPassword: get('btn-link-forgot-password'),
            linkGotoRegister: get('btn-link-goto-register'),
            loginEmailError: get('auth-login-email-error'),
            loginPasswordError: get('auth-login-password-error'),

            // Register form
            formRegister: get('form-auth-register'),
            registerName: get('auth-register-name'),
            registerEmail: get('auth-register-email'),
            registerPassword: get('auth-register-password'),
            registerPasswordToggle: get('auth-register-password-toggle'),
            registerConfirmPassword: get('auth-register-confirm-password'),
            registerConfirmToggle: get('auth-register-confirm-toggle'),
            registerTerms: get('auth-register-terms'),
            btnRegisterSubmit: get('btn-auth-register-submit'),
            btnRegisterText: get('btn-auth-register-text'),
            btnRegisterSpinner: get('btn-auth-register-spinner'),
            linkGotoLogin: get('btn-link-goto-login'),
            registerNameError: get('auth-register-name-error'),
            registerEmailError: get('auth-register-email-error'),
            registerPasswordError: get('auth-register-password-error'),
            registerConfirmError: get('auth-register-confirm-error'),
            registerTermsError: get('auth-register-terms-error'),

            // Password requirement indicators
            reqMinLength: get('pw-req-length'),
            reqUppercase: get('pw-req-uppercase'),
            reqNumber: get('pw-req-number'),

            // Forgot form
            formForgot: get('form-auth-forgot'),
            forgotEmail: get('auth-forgot-email'),
            forgotEmailError: get('auth-forgot-email-error'),
            btnForgotSubmit: get('btn-auth-forgot-submit'),
            btnForgotText: get('btn-auth-forgot-text'),
            btnForgotSpinner: get('btn-auth-forgot-spinner'),
            btnForgotBack: get('btn-auth-forgot-back'),

            // Forgot success
            forgotSuccessEmailDisplay: get('auth-forgot-success-email'),
            btnForgotSuccessBack: get('btn-auth-forgot-success-back'),
            btnForgotResend: get('btn-auth-forgot-resend'),
            forgotResendTimer: get('auth-forgot-resend-timer'),

            // Sidebar elements
            sidebarAuthGuest: get('sidebar-auth-guest'),
            btnSidebarLogin: get('btn-sidebar-login'),
            sidebarAuthUser: get('sidebar-auth-user'),
            userAvatarBadge: get('user-avatar-badge'),
            userNameDisplay: get('user-name-display'),
            userEmailDisplay: get('user-email-display'),
            accountMenuBtn: get('btn-account-menu-toggle'),
            accountPopoverMenu: get('account-popover-menu'),
            menuAvatarBadge: get('menu-avatar-badge'),
            menuNameDisplay: get('menu-name-display'),
            menuEmailDisplay: get('menu-email-display'),
            btnMenuLogout: get('btn-menu-logout')
        };
    }

    bindEvents() {
        if (!this.dom || !this.dom.dialog) return;

        // Dialog close & backdrop click
        if (this.dom.btnCloseDialog) {
            this.dom.btnCloseDialog.addEventListener('click', () => this.closeAuthModal());
        }

        this.dom.dialog.addEventListener('click', (e) => {
            const rect = this.dom.panel ? this.dom.panel.getBoundingClientRect() : null;
            if (rect) {
                const isInPanel = (
                    rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
                    rect.left <= e.clientX && e.clientX <= rect.left + rect.width
                );
                if (!isInPanel) this.closeAuthModal();
            }
        });

        this.dom.dialog.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                this.closeAuthModal();
            }
        });

        // Tabs
        if (this.dom.tabLogin) {
            this.dom.tabLogin.addEventListener('click', () => this.switchTab('login'));
        }
        if (this.dom.tabRegister) {
            this.dom.tabRegister.addEventListener('click', () => this.switchTab('register'));
        }

        // Links between modes
        if (this.dom.linkForgotPassword) {
            this.dom.linkForgotPassword.addEventListener('click', (e) => {
                e.preventDefault();
                this.switchTab('forgot');
            });
        }
        if (this.dom.linkGotoRegister) {
            this.dom.linkGotoRegister.addEventListener('click', (e) => {
                e.preventDefault();
                this.switchTab('register');
            });
        }
        if (this.dom.linkGotoLogin) {
            this.dom.linkGotoLogin.addEventListener('click', (e) => {
                e.preventDefault();
                this.switchTab('login');
            });
        }
        if (this.dom.btnForgotBack) {
            this.dom.btnForgotBack.addEventListener('click', (e) => {
                e.preventDefault();
                this.switchTab('login');
            });
        }
        if (this.dom.btnForgotSuccessBack) {
            this.dom.btnForgotSuccessBack.addEventListener('click', (e) => {
                e.preventDefault();
                this.switchTab('login');
            });
        }
        if (this.dom.btnForgotResend) {
            this.dom.btnForgotResend.addEventListener('click', (e) => {
                e.preventDefault();
                this.handleResendForgot();
            });
        }

        // Password toggles
        if (this.dom.loginPasswordToggle) {
            this.dom.loginPasswordToggle.addEventListener('click', () => {
                this.togglePasswordVisibility(this.dom.loginPassword, this.dom.loginPasswordToggle);
            });
        }
        if (this.dom.registerPasswordToggle) {
            this.dom.registerPasswordToggle.addEventListener('click', () => {
                this.togglePasswordVisibility(this.dom.registerPassword, this.dom.registerPasswordToggle);
            });
        }
        if (this.dom.registerConfirmToggle) {
            this.dom.registerConfirmToggle.addEventListener('click', () => {
                this.togglePasswordVisibility(this.dom.registerConfirmPassword, this.dom.registerConfirmToggle);
            });
        }

        // Real-time password requirement checklist
        if (this.dom.registerPassword) {
            this.dom.registerPassword.addEventListener('input', () => {
                this.validatePasswordRequirements(this.dom.registerPassword.value);
            });
        }

        // Form submits
        if (this.dom.formLogin) {
            this.dom.formLogin.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleLoginSubmit();
            });
        }
        if (this.dom.formRegister) {
            this.dom.formRegister.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleRegisterSubmit();
            });
        }
        if (this.dom.formForgot) {
            this.dom.formForgot.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleForgotSubmit();
            });
        }

        // Google OAuth
        if (this.dom.btnGoogle) {
            this.dom.btnGoogle.addEventListener('click', () => this.handleGoogleAuth());
        }

        // Sidebar trigger
        if (this.dom.btnSidebarLogin) {
            this.dom.btnSidebarLogin.addEventListener('click', (e) => {
                this.openAuthModal('login', null, e.currentTarget);
            });
        }

        // Account popover
        if (this.dom.accountMenuBtn) {
            this.dom.accountMenuBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleAccountMenu();
            });
        }
        if (this.dom.sidebarAuthUser) {
            this.dom.sidebarAuthUser.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleAccountMenu();
            });
        }

        // Logout
        if (this.dom.btnMenuLogout) {
            this.dom.btnMenuLogout.addEventListener('click', (e) => {
                e.preventDefault();
                this.handleLogout();
            });
        }

        // Close account popover when clicking outside
        if (typeof document !== 'undefined') {
            document.addEventListener('click', (e) => {
                if (this.dom.accountPopoverMenu && !this.dom.accountPopoverMenu.classList.contains('hidden')) {
                    if (!this.dom.accountPopoverMenu.contains(e.target) && !this.dom.sidebarAuthUser.contains(e.target)) {
                        this.closeAccountMenu();
                    }
                }
            });
        }
    }

    openAuthModal(tab = 'login', pendingAction = null, triggerElement = null) {
        if (triggerElement) {
            this.triggerElement = triggerElement;
        }
        if (pendingAction) {
            this.setPendingAction(pendingAction);
        }
        this.clearErrors();
        this.switchTab(tab);
        if (this.dom.dialog && typeof this.dom.dialog.showModal === 'function') {
            if (!this.dom.dialog.open) {
                this.dom.dialog.showModal();
            }
        }
        // Focus initial field
        setTimeout(() => {
            if (tab === 'login' && this.dom.loginEmail && typeof this.dom.loginEmail.focus === 'function') {
                this.dom.loginEmail.focus();
            } else if (tab === 'register' && this.dom.registerName && typeof this.dom.registerName.focus === 'function') {
                this.dom.registerName.focus();
            } else if (tab === 'forgot' && this.dom.forgotEmail && typeof this.dom.forgotEmail.focus === 'function') {
                this.dom.forgotEmail.focus();
            }
        }, 50);
    }

    closeAuthModal() {
        if (this.dom && this.dom.dialog && this.dom.dialog.open && typeof this.dom.dialog.close === 'function') {
            this.dom.dialog.close();
        }
        this.clearErrors();
        if (this.resendCountdownInterval) {
            clearInterval(this.resendCountdownInterval);
            this.resendCountdownInterval = null;
        }
        if (this.triggerElement && typeof this.triggerElement.focus === 'function') {
            this.triggerElement.focus();
            this.triggerElement = null;
        }
    }

    switchTab(tab) {
        this.activeTab = tab;
        this.clearErrors();

        // Update tabs active visual
        const isLogin = tab === 'login';
        const isRegister = tab === 'register';
        const isForgot = tab === 'forgot';
        const isForgotSuccess = tab === 'forgot-success';

        if (this.dom.tabLogin) {
            this.dom.tabLogin.classList.toggle('active', isLogin);
            this.dom.tabLogin.setAttribute('aria-selected', isLogin ? 'true' : 'false');
        }
        if (this.dom.tabRegister) {
            this.dom.tabRegister.classList.toggle('active', isRegister);
            this.dom.tabRegister.setAttribute('aria-selected', isRegister ? 'true' : 'false');
        }

        // Show/hide sections
        if (this.dom.tabsContainer) {
            this.dom.tabsContainer.classList.toggle('hidden', isForgot || isForgotSuccess);
        }
        if (this.dom.sectionOAuth) {
            this.dom.sectionOAuth.classList.toggle('hidden', isForgot || isForgotSuccess);
        }
        if (this.dom.sectionDivider) {
            this.dom.sectionDivider.classList.toggle('hidden', isForgot || isForgotSuccess);
        }

        if (this.dom.sectionLogin) this.dom.sectionLogin.classList.toggle('hidden', !isLogin);
        if (this.dom.sectionRegister) this.dom.sectionRegister.classList.toggle('hidden', !isRegister);
        if (this.dom.sectionForgot) this.dom.sectionForgot.classList.toggle('hidden', !isForgot);
        if (this.dom.sectionForgotSuccess) this.dom.sectionForgotSuccess.classList.toggle('hidden', !isForgotSuccess);

        // Update header texts
        if (isLogin) {
            if (this.dom.dialogTitle) this.dom.dialogTitle.innerText = 'Đăng nhập vào AI Story Engine';
            if (this.dom.dialogDesc) this.dom.dialogDesc.innerText = 'Tiếp tục hành trình sáng tác cùng trợ lý AI của bạn';
        } else if (isRegister) {
            if (this.dom.dialogTitle) this.dom.dialogTitle.innerText = 'Tạo tài khoản AI Story Engine';
            if (this.dom.dialogDesc) this.dom.dialogDesc.innerText = 'Bắt đầu sáng tác và đồng bộ các chương truyện dài hạn';
        } else if (isForgot) {
            if (this.dom.dialogTitle) this.dom.dialogTitle.innerText = 'Quên mật khẩu?';
            if (this.dom.dialogDesc) this.dom.dialogDesc.innerText = 'Nhập email tài khoản để nhận liên kết khôi phục an toàn';
        } else if (isForgotSuccess) {
            if (this.dom.dialogTitle) this.dom.dialogTitle.innerText = 'Kiểm tra hộp thư của bạn';
            if (this.dom.dialogDesc) this.dom.dialogDesc.innerText = 'Chúng tôi đã gửi liên kết khôi phục nếu tài khoản tồn tại';
        }
    }

    togglePasswordVisibility(input, button) {
        if (!input) return;
        const isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';
        if (button) {
            button.setAttribute('aria-label', isPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
            button.title = isPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu';
            const iconSvg = button.querySelector('svg');
            if (iconSvg) {
                iconSvg.innerHTML = isPassword
                    ? `<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>`
                    : `<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>`;
            }
        }
    }

    validateEmail(email) {
        if (!email || typeof email !== 'string') return false;
        const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return re.test(email.trim());
    }

    validatePasswordRequirements(password) {
        const str = password || '';
        const minLength = str.length >= 8;
        const hasUpper = /[A-Z]/.test(str);
        const hasNumber = /[0-9]/.test(str);

        if (this.dom && this.dom.reqMinLength) {
            this.dom.reqMinLength.classList.toggle('satisfied', minLength);
        }
        if (this.dom && this.dom.reqUppercase) {
            this.dom.reqUppercase.classList.toggle('satisfied', hasUpper);
        }
        if (this.dom && this.dom.reqNumber) {
            this.dom.reqNumber.classList.toggle('satisfied', hasNumber);
        }

        return minLength && hasUpper && hasNumber;
    }

    clearErrors() {
        if (!this.dom) return;
        if (this.dom.globalAlert) {
            this.dom.globalAlert.classList.add('hidden');
            this.dom.globalAlert.innerText = '';
        }

        const errorElements = [
            this.dom.loginEmailError, this.dom.loginPasswordError,
            this.dom.registerNameError, this.dom.registerEmailError,
            this.dom.registerPasswordError, this.dom.registerConfirmError,
            this.dom.registerTermsError, this.dom.forgotEmailError
        ];
        errorElements.forEach(el => {
            if (el) {
                el.innerText = '';
                el.classList.add('hidden');
            }
        });

        const inputs = [
            this.dom.loginEmail, this.dom.loginPassword,
            this.dom.registerName, this.dom.registerEmail,
            this.dom.registerPassword, this.dom.registerConfirmPassword,
            this.dom.forgotEmail
        ];
        inputs.forEach(input => {
            if (input) {
                input.classList.remove('input-error');
                input.removeAttribute('aria-invalid');
            }
        });
    }

    setFieldError(input, errorEl, message) {
        if (input) {
            input.classList.add('input-error');
            input.setAttribute('aria-invalid', 'true');
        }
        if (errorEl) {
            errorEl.innerText = message;
            errorEl.classList.remove('hidden');
        }
    }

    showGlobalAlert(message, type = 'error') {
        if (!this.dom.globalAlert) return;
        this.dom.globalAlert.className = `auth-alert auth-alert-${type}`;
        this.dom.globalAlert.innerText = message;
        this.dom.globalAlert.classList.remove('hidden');
    }

    setLoading(btn, spinner, textEl, loadingText, isLoading) {
        if (!btn) return;
        btn.disabled = isLoading;
        if (spinner) spinner.classList.toggle('hidden', !isLoading);
        if (textEl && loadingText) {
            if (isLoading) {
                textEl.dataset.origText = textEl.innerText;
                textEl.innerText = loadingText;
            } else if (textEl.dataset.origText) {
                textEl.innerText = textEl.dataset.origText;
            }
        }
    }

    async handleLoginSubmit() {
        this.clearErrors();
        const email = this.dom.loginEmail ? this.dom.loginEmail.value.trim() : '';
        const password = this.dom.loginPassword ? this.dom.loginPassword.value : '';
        const remember = this.dom.loginRemember ? this.dom.loginRemember.checked : true;

        let hasError = false;
        if (!email) {
            this.setFieldError(this.dom.loginEmail, this.dom.loginEmailError, 'Vui lòng nhập email của bạn.');
            hasError = true;
        } else if (!this.validateEmail(email)) {
            this.setFieldError(this.dom.loginEmail, this.dom.loginEmailError, 'Định dạng email chưa hợp lệ (ví dụ: tacgia@example.com).');
            hasError = true;
        }

        if (!password) {
            this.setFieldError(this.dom.loginPassword, this.dom.loginPasswordError, 'Vui lòng nhập mật khẩu.');
            hasError = true;
        }

        if (hasError) return;

        this.setLoading(this.dom.btnLoginSubmit, this.dom.btnLoginSpinner, this.dom.btnLoginText, 'Đang đăng nhập...', true);

        try {
            const res = await fetch('/api/v1/auth/login', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email,
                    password,
                    remember_me: remember
                })
            });

            const json = await res.json().catch(() => ({}));
            if (!res.ok) {
                const message = json.detail?.message || json.message || 'Email hoặc mật khẩu chưa chính xác. Vui lòng kiểm tra lại.';
                this.showGlobalAlert(message, 'error');
                return;
            }

            const backendUser = json.data?.user || {};
            const user = {
                id: backendUser.id,
                displayName: backendUser.display_name || email.split('@')[0],
                email: backendUser.email || email,
                avatar: backendUser.avatar_url || null,
                tier: 'Tác giả'
            };

            this.saveUser(user, remember);
            this.syncSidebarUI();
            this.finishAuthSuccess(user);
        } catch (error) {
            this.showGlobalAlert('Không thể kết nối đến máy chủ. Vui lòng thử lại.', 'error');
        } finally {
            this.setLoading(this.dom.btnLoginSubmit, this.dom.btnLoginSpinner, this.dom.btnLoginText, '', false);
        }
    }

    async handleRegisterSubmit() {
        this.clearErrors();
        const name = this.dom.registerName ? this.dom.registerName.value.trim() : '';
        const email = this.dom.registerEmail ? this.dom.registerEmail.value.trim() : '';
        const password = this.dom.registerPassword ? this.dom.registerPassword.value : '';
        const confirm = this.dom.registerConfirmPassword ? this.dom.registerConfirmPassword.value : '';
        const agreed = this.dom.registerTerms ? this.dom.registerTerms.checked : false;

        let hasError = false;
        if (!name) {
            this.setFieldError(this.dom.registerName, this.dom.registerNameError, 'Vui lòng nhập bút danh hoặc tên hiển thị.');
            hasError = true;
        }

        if (!email) {
            this.setFieldError(this.dom.registerEmail, this.dom.registerEmailError, 'Vui lòng nhập email.');
            hasError = true;
        } else if (!this.validateEmail(email)) {
            this.setFieldError(this.dom.registerEmail, this.dom.registerEmailError, 'Định dạng email chưa hợp lệ (ví dụ: tacgia@example.com).');
            hasError = true;
        }

        if (!password) {
            this.setFieldError(this.dom.registerPassword, this.dom.registerPasswordError, 'Vui lòng tạo mật khẩu.');
            hasError = true;
        } else if (!this.validatePasswordRequirements(password)) {
            this.setFieldError(this.dom.registerPassword, this.dom.registerPasswordError, 'Mật khẩu cần tối thiểu 8 ký tự, gồm ít nhất 1 chữ hoa và 1 số.');
            hasError = true;
        }

        if (!confirm) {
            this.setFieldError(this.dom.registerConfirmPassword, this.dom.registerConfirmError, 'Vui lòng xác nhận mật khẩu.');
            hasError = true;
        } else if (password !== confirm) {
            this.setFieldError(this.dom.registerConfirmPassword, this.dom.registerConfirmError, 'Mật khẩu xác nhận không khớp với mật khẩu đã nhập.');
            hasError = true;
        }

        if (!agreed) {
            if (this.dom.registerTermsError) {
                this.dom.registerTermsError.innerText = 'Bạn cần đồng ý với Điều khoản để tiếp tục.';
                this.dom.registerTermsError.classList.remove('hidden');
            }
            hasError = true;
        }

        if (hasError) return;

        this.setLoading(this.dom.btnRegisterSubmit, this.dom.btnRegisterSpinner, this.dom.btnRegisterText, 'Đang tạo tài khoản...', true);

        try {
            const res = await fetch('/api/v1/auth/register', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    display_name: name,
                    email: email,
                    password: password,
                    confirm_password: confirm,
                    terms_agreed: agreed
                })
            });

            const json = await res.json().catch(() => ({}));
            if (!res.ok) {
                const message = json.detail?.message || json.message || 'Không thể tạo tài khoản lúc này. Vui lòng thử lại.';
                this.showGlobalAlert(message, 'error');
                return;
            }

            const backendUser = json.data?.user || {};
            const user = {
                id: backendUser.id,
                displayName: backendUser.display_name || name,
                email: backendUser.email || email,
                avatar: backendUser.avatar_url || null,
                tier: 'Tác giả mới'
            };

            this.saveUser(user, true);
            this.syncSidebarUI();
            this.finishAuthSuccess(user);
        } catch (error) {
            this.showGlobalAlert('Không thể kết nối đến máy chủ. Vui lòng thử lại.', 'error');
        } finally {
            this.setLoading(this.dom.btnRegisterSubmit, this.dom.btnRegisterSpinner, this.dom.btnRegisterText, '', false);
        }
    }

    async handleForgotSubmit() {
        this.clearErrors();
        const email = this.dom.forgotEmail ? this.dom.forgotEmail.value.trim() : '';

        if (!email) {
            this.setFieldError(this.dom.forgotEmail, this.dom.forgotEmailError, 'Vui lòng nhập email tài khoản của bạn.');
            return;
        }
        if (!this.validateEmail(email)) {
            this.setFieldError(this.dom.forgotEmail, this.dom.forgotEmailError, 'Định dạng email chưa hợp lệ.');
            return;
        }

        this.setLoading(this.dom.btnForgotSubmit, this.dom.btnForgotSpinner, this.dom.btnForgotText, 'Đang gửi...', true);

        try {
            await fetch('/api/v1/auth/forgot-password', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });

            if (this.dom.forgotSuccessEmailDisplay) {
                this.dom.forgotSuccessEmailDisplay.innerText = email;
            }

            this.switchTab('forgot-success');
            this.startResendCountdown();
        } catch (error) {
            this.showGlobalAlert('Không thể gửi email lúc này. Vui lòng thử lại sau.', 'error');
        } finally {
            this.setLoading(this.dom.btnForgotSubmit, this.dom.btnForgotSpinner, this.dom.btnForgotText, '', false);
        }
    }

    startResendCountdown() {
        if (this.resendCountdownInterval) clearInterval(this.resendCountdownInterval);
        this.resendSecondsLeft = 60;
        if (this.dom.btnForgotResend) this.dom.btnForgotResend.disabled = true;
        if (this.dom.forgotResendTimer) this.dom.forgotResendTimer.innerText = `(${this.resendSecondsLeft}s)`;

        this.resendCountdownInterval = setInterval(() => {
            this.resendSecondsLeft--;
            if (this.resendSecondsLeft <= 0) {
                clearInterval(this.resendCountdownInterval);
                this.resendCountdownInterval = null;
                if (this.dom.btnForgotResend) this.dom.btnForgotResend.disabled = false;
                if (this.dom.forgotResendTimer) this.dom.forgotResendTimer.innerText = '';
            } else {
                if (this.dom.forgotResendTimer) this.dom.forgotResendTimer.innerText = `(${this.resendSecondsLeft}s)`;
            }
        }, 1000);
    }

    handleResendForgot() {
        if (this.resendSecondsLeft > 0) return;
        this.startResendCountdown();
        this.showGlobalAlert('Đã gửi lại liên kết khôi phục vào email.', 'info');
    }

    handleGoogleAuth() {
        this.clearErrors();
        this.setLoading(this.dom.btnGoogle, this.dom.googleSpinner, this.dom.googleBtnText, 'Đang kết nối Google...', true);
        window.location.assign('/api/v1/auth/google/start');
    }

    finishAuthSuccess(user) {
        const action = this.pendingAction;
        this.setPendingAction(null);
        this.closeAuthModal();

        if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('ai-story-auth-changed', {
                detail: { user, action }
            }));
        }

        if (typeof this.onAuthSuccessCallback === 'function') {
            this.onAuthSuccessCallback({ user, action });
        }
    }

    async handleLogout() {
        this.clearUser();
        this.closeAccountMenu();
        this.syncSidebarUI();
        if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('ai-story-auth-changed', {
                detail: { user: null, action: null }
            }));
        }

        try {
            if (typeof fetch !== 'undefined' && typeof window !== 'undefined') {
                await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'same-origin' });
            }
        } catch (e) {
            console.warn('Lỗi khi gọi logout API:', e);
        }
    }

    syncSidebarUI() {
        if (!this.dom) return;
        const isAuth = this.isAuthenticated();
        const user = this.getCurrentUser();

        if (this.dom.sidebarAuthGuest) {
            this.dom.sidebarAuthGuest.classList.toggle('hidden', isAuth);
        }
        if (this.dom.sidebarAuthUser) {
            this.dom.sidebarAuthUser.classList.toggle('hidden', !isAuth);
        }

        if (isAuth && user) {
            const initials = this.getInitials(user.displayName || user.email);
            if (this.dom.userAvatarBadge) this.dom.userAvatarBadge.innerText = initials;
            if (this.dom.userNameDisplay) this.dom.userNameDisplay.innerText = user.displayName || 'Tác giả';
            if (this.dom.userEmailDisplay) this.dom.userEmailDisplay.innerText = user.email || '';

            if (this.dom.menuAvatarBadge) this.dom.menuAvatarBadge.innerText = initials;
            if (this.dom.menuNameDisplay) this.dom.menuNameDisplay.innerText = user.displayName || 'Tác giả';
            if (this.dom.menuEmailDisplay) this.dom.menuEmailDisplay.innerText = user.email || '';
        }
    }

    getInitials(str) {
        if (!str) return 'TG';
        const parts = str.trim().split(/\s+/);
        if (parts.length >= 2) {
            return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
        }
        return str.slice(0, 2).toUpperCase();
    }

    toggleAccountMenu() {
        if (!this.dom || !this.dom.accountPopoverMenu) return;
        const isHidden = this.dom.accountPopoverMenu.classList.contains('hidden');
        if (isHidden) {
            this.dom.accountPopoverMenu.classList.remove('hidden');
        } else {
            this.dom.accountPopoverMenu.classList.add('hidden');
        }
    }

    closeAccountMenu() {
        if (this.dom && this.dom.accountPopoverMenu) {
            this.dom.accountPopoverMenu.classList.add('hidden');
        }
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AuthController;
}
