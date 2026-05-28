/**
 * NetraNext API Configuration
 * Configure the connection to the NetraNext central server
 */
// production step
window.NetraNextConfig = {
    // Central Server API Configuration
    apiBaseUrl: 'https://netranext.m.frappe.cloud',
       // apiBaseUrl: 'http://netranext-service.local:8000',

    apiVersion: 'v1',

    // API Endpoints
    endpoints: {
        dashboard: '/api/method/netranext.apis.v1.dashboard.get_dashboard_data',
        journeys: '/api/method/netranext.apis.v1.dashboard.get_dashboard_data',
        attendance: '/api/method/netranext.apis.v1.dashboard.get_dashboard_data'
    },

    // Connection Settings
    timeout: 30000, // 30 seconds
    retryAttempts: 3,
    retryDelay: 1000 // 1 second
};

// Helper function to get full API URL
function getNetraNextApiUrl(endpoint) {
    return window.NetraNextConfig.apiBaseUrl + endpoint;
}

// Helper function to make API calls to NetraNext server
function callNetraNextApi(endpoint, data, successCallback, errorCallback) {
    $.ajax({
        url: getNetraNextApiUrl(endpoint),
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data || {}),
        timeout: window.NetraNextConfig.timeout,
        success: function(response) {
            if (typeof successCallback === 'function') {
                successCallback(response);
            }
        },
        error: function(xhr, status, error) {
            if (typeof errorCallback === 'function') {
                errorCallback(xhr, status, error);
            }
        }
    });
}
