/* 
 * DocuIntel - Authentication Page Logic
 * Handles tab toggles, form submits, and simple error display.
 * Simple code structure with casual student comments.
 */

document.addEventListener('DOMContentLoaded', () => {
    // Check if we are already logged in, redirect to workspace if so
    if (api.accessToken) {
        window.location.href = 'app.html';
        return;
    }

    const loginTab = document.getElementById('login-tab');
    const registerTab = document.getElementById('register-tab');
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    const errorAlert = document.getElementById('error-alert');
    const errorMessage = document.getElementById('error-message');
    const successAlert = document.getElementById('success-alert');

    // UI helpers to show errors or success popups
    function showError(msg) {
        errorMessage.textContent = msg;
        errorAlert.classList.remove('hidden');
        successAlert.classList.add('hidden');
    }

    function showSuccess() {
        errorAlert.classList.add('hidden');
        successAlert.classList.remove('hidden');
    }

    function clearAlerts() {
        errorAlert.classList.add('hidden');
        successAlert.classList.add('hidden');
    }

    // Switch view to Sign In form
    loginTab.addEventListener('click', () => {
        loginTab.classList.add('active');
        registerTab.classList.remove('active');
        loginForm.classList.remove('hidden');
        registerForm.classList.add('hidden');
        clearAlerts();
    });

    // Switch view to Register form
    registerTab.addEventListener('click', () => {
        registerTab.classList.add('active');
        loginTab.classList.remove('active');
        registerForm.classList.remove('hidden');
        loginForm.classList.add('hidden');
        clearAlerts();
    });

    // Sign In form handler
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearAlerts();
        
        const email = document.getElementById('login-email').value;
        const password = document.getElementById('login-password').value;
        const submitBtn = document.getElementById('btn-login-submit');

        try {
            // Disable button and show spinner-like state
            submitBtn.disabled = true;
            submitBtn.querySelector('span').textContent = 'Signing in...';

            await api.login(email, password);
            console.log('Logged in successfully! Redirecting...');
            window.location.href = 'app.html';
        } catch (err) {
            console.error('Login error:', err);
            showError(err.message || 'Invalid email or password.');
            submitBtn.disabled = false;
            submitBtn.querySelector('span').textContent = 'Sign In';
        }
    });

    // Registration form handler
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearAlerts();

        const name = document.getElementById('reg-name').value;
        const email = document.getElementById('reg-email').value;
        const password = document.getElementById('reg-password').value;
        const submitBtn = document.getElementById('btn-register-submit');

        if (password.length < 8) {
            showError('Password must be at least 8 characters long.');
            return;
        }

        try {
            submitBtn.disabled = true;
            submitBtn.querySelector('span').textContent = 'Creating account...';

            await api.register(email, password, name);
            showSuccess();
            
            // Switch user back to login tab automatically
            setTimeout(() => {
                loginTab.click();
                document.getElementById('login-email').value = email;
                document.getElementById('login-password').focus();
            }, 1500);
        } catch (err) {
            console.error('Register error:', err);
            showError(err.message || 'Email might already be taken.');
        } finally {
            submitBtn.disabled = false;
            submitBtn.querySelector('span').textContent = 'Create Account';
        }
    });
});
