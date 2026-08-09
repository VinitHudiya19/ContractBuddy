/* Contract Buddy - Auth Page
 * Login and registration form handlers.
 */

document.addEventListener('DOMContentLoaded', function() {
    // grab DOM elements
    var loginTab = document.getElementById('login-tab');
    var registerTab = document.getElementById('register-tab');
    var loginForm = document.getElementById('login-form');
    var registerForm = document.getElementById('register-form');
    var errorAlert = document.getElementById('error-alert');
    var errorMessage = document.getElementById('error-message');
    var successAlert = document.getElementById('success-alert');

    // helper: show error message
    function showError(msg) {
        errorMessage.textContent = msg;
        errorAlert.classList.remove('hidden');
        successAlert.classList.add('hidden');
    }

    // helper: show success message  
    function showSuccess() {
        successAlert.classList.remove('hidden');
        errorAlert.classList.add('hidden');
    }

    // helper: clear all alerts
    function clearAlerts() {
        errorAlert.classList.add('hidden');
        successAlert.classList.add('hidden');
    }

    // tab switching
    loginTab.addEventListener('click', function() {
        clearAlerts();
        loginTab.classList.add('active');
        registerTab.classList.remove('active');
        loginForm.classList.remove('hidden');
        registerForm.classList.add('hidden');
    });

    registerTab.addEventListener('click', function() {
        clearAlerts();
        registerTab.classList.add('active');
        loginTab.classList.remove('active');
        registerForm.classList.remove('hidden');
        loginForm.classList.add('hidden');
    });

    // login form submit
    loginForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        clearAlerts();
        var email = document.getElementById('login-email').value.trim();
        var password = document.getElementById('login-password').value;
        var submitBtn = document.getElementById('btn-login-submit');

        if (!email || !password) {
            showError('Please fill in all fields.');
            return;
        }

        try {
            submitBtn.disabled = true;
            submitBtn.querySelector('span').textContent = 'Signing in...';
            await api.login(email, password);
            window.location.href = 'app.html';
        } catch (err) {
            showError(err.message || 'Invalid email or password.');
        } finally {
            submitBtn.disabled = false;
            submitBtn.querySelector('span').textContent = 'Sign In';
        }
    });

    // register form submit
    registerForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        clearAlerts();

        var name = document.getElementById('reg-name').value.trim();
        var email = document.getElementById('reg-email').value.trim();
        var password = document.getElementById('reg-password').value;
        var submitBtn = document.getElementById('btn-register-submit');

        if (!name || !email || !password) {
            showError('Please fill in all fields.');
            return;
        }

        if (password.length < 8) {
            showError('Password must be at least 8 characters long.');
            return;
        }

        try {
            submitBtn.disabled = true;
            submitBtn.querySelector('span').textContent = 'Creating account...';
            // api.register takes (email, password, fullName)
            await api.register(email, password, name);
            showSuccess();

            // switch to login tab after a bit so they can sign in
            setTimeout(function() {
                loginTab.click();
                document.getElementById('login-email').value = email;
                document.getElementById('login-password').focus();
            }, 1500);
        } catch (err) {
            showError(err.message || 'Email might already be taken.');
        } finally {
            submitBtn.disabled = false;
            submitBtn.querySelector('span').textContent = 'Create Account';
        }
    });
});
