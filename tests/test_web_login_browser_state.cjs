// Run actual checked-out Frappe handlers with simulated browser state; no browser/server required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const framework = path.resolve(__dirname, '../../frappe/frappe');
const loginSource = fs.readFileSync(path.join(framework, 'templates/includes/login/login.js'), 'utf8');
const start = loginSource.indexOf('var login_handlers = {');
const end = loginSource.indexOf('return login_handlers;', start);
assert(start >= 0 && end > start, 'Native login handler must be present');
const handlerSource = loginSource.slice(start, end)
    .replace(/{{[\s\S]*?}}/g, '"translation"')
    .replace(/{%[\s\S]*?%}/g, '') + '\nlogin_handlers[200];';

function loginDestination({ home = '/app', redirect = '', message = 'Logged In', storage = {} } = {}) {
    const context = {
        login: { set_status() {} }, get_error_handler: () => () => {},
        document: { body: { innerHTML: '' } }, window: { location: { href: '', hash: '' } },
        frappe: { utils: { get_url_arg: () => redirect, sanitise_redirect: value => value } },
        localStorage: { getItem: key => storage[key], removeItem: key => delete storage[key] }
    };
    const handler = vm.runInNewContext(handlerSource, context);
    handler({ message, home_page: home });
    return context.window.location.href;
}

// Fresh and incognito-like contexts do not acquire an application workspace redirect.
assert.equal(loginDestination(), '/app');
assert.equal(loginDestination({ storage: {} }), '/app');
// Requested deep links retain priority over the framework's computed landing path.
assert.equal(loginDestination({ redirect: '/app/netranext' }), '/app/netranext');
assert.equal(loginDestination({ redirect: '/app/customer/CUST-1' }), '/app/customer/CUST-1');
// Website users retain the native portal branch and last-visited behavior.
assert.equal(loginDestination({ message: 'No App', home: '/me' }), '/me');
assert.equal(loginDestination({ message: 'No App', home: '/me', storage: { last_visited: '/orders' } }), '/orders');

const workspaceSource = fs.readFileSync(path.join(framework, 'public/js/frappe/views/workspace/workspace.js'), 'utf8');
const workspaceStart = workspaceSource.indexOf('get_page_to_show() {');
const workspaceEnd = workspaceSource.indexOf('\n\tasync show_page(', workspaceStart);
assert(workspaceStart >= 0 && workspaceEnd > workspaceStart, 'Native workspace selection must be present');
const method = '({' + workspaceSource.slice(workspaceStart, workspaceEnd) + '}).get_page_to_show;';
function workspacePage({ saved = {}, preference = null, route = [], pages = [
    { title: 'Home', public: true }, { title: 'NetraNext', public: true }
] } = {}) {
    const context = { localStorage: saved, frappe: {
        boot: { user: { default_workspace: preference } }, get_route: () => route
    } };
    return vm.runInNewContext(method, context).call({ all_pages: pages });
}
assert.equal(workspacePage().name, 'Home');
assert.equal(workspacePage({ saved: {} }).name, 'Home');
assert.equal(workspacePage({ saved: { current_page: 'NetraNext' } }).name, 'NetraNext');
assert.equal(workspacePage({ saved: { current_page: 'NetraNext' }, preference: { title: 'Accounting', public: true } }).name, 'Accounting');
assert.equal(workspacePage({ preference: { title: 'Home', public: true }, route: ['Workspaces', 'NetraNext'] }).name, 'NetraNext');
const returningBrowser = { current_page: 'NetraNext' };
assert.equal(workspacePage({ saved: returningBrowser }).name, 'NetraNext');
assert.equal(workspacePage({ saved: returningBrowser }).name, 'NetraNext'); // logout does not erase native browser preferences
// With no accessible Home, Frappe can choose its first accessible workspace.
assert.equal(workspacePage({ pages: [{ title: 'NetraNext', public: true }] }).name, 'NetraNext');
console.log('Native login/browser-state routing assertions passed (simulated browser; not a live UI test).');
