// auth_guard.js — 页面级鉴权守卫
// 在 <head> 中同步执行，阻止未授权用户看到页面内容

/**
 * 核心查票函数
 * @param {string} requiredRole - 访问该页面需要的角色 ('SuperAdmin' 或 'SchoolAdmin')
 */
function checkAuth(requiredRole) {
    const token = localStorage.getItem('access_token');
    const role = localStorage.getItem('user_role');

    // 没有 token，踢回登录页
    if (!token) {
        window.location.replace('/login.html');
        return false;
    }

    // 角色不匹配，清除凭证并跳回登录页重新登录
    if (requiredRole && role !== requiredRole) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user_role');
        localStorage.removeItem('username');
        localStorage.removeItem('school_id');
        window.location.replace('/login.html');
        return false;
    }

    return true;
}

/**
 * 统一退出登录
 */
function logout() {
    ['access_token', 'user_role', 'username', 'school_id'].forEach(k => localStorage.removeItem(k));
    window.location.replace('/login.html');
}
