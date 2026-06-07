const config = {
    clientKey: 'YOUR_YESCAPTCHA_CLIENT_KEY', // Your purchased YesCaptcha client key
    host: 'https://api.yescaptcha.com', // API server address, default is official server https://api.yescaptcha.com

    autorun: true, // Auto-run true or false
    // Deprecated
    imageclassification: true, // (Deprecated!!!) reCaptcha automatic recognition
    hcaptcha: true, // hCaptcha automatic recognition
    imagetotext: true, // Coinlist English/digit automatic recognition
    rainbow: true, // Coinlist queue pink button auto-click
    times: 200, // Time interval between image clicks, in milliseconds
    isTextCaptcha: false, // Enable text captcha recognition
    endTimes: '20', // Stop recognition after this many attempts
    isAutoClickCheckBox: true, // Whether to auto-click checkbox
    checkBoxClickDelayTime: "500", // Delay after page load before auto-clicking checkbox
    isOpenEndTimes: true, // Enable recognition attempt limit feature
    isOpenCloudflare: false, // Enable Cloudflare verification
    isOpenCloudflareTurnstileProtocol: false, // Enable Cloudflare Turnstile protocol version
    isAutoSubmit: true, // Auto-click submit button in 3x3 grid verification
    autoSubmitDelayTime: 100, // Delay before auto-submit, in milliseconds
    autoSubmitDelayFloatRate: 0.1, // Auto-submit delay variation rate, 0~1
    workStatusFlag: '',
    jsControlObjectName: 'yesCaptcha',
    allowJsInject: false,
    network: { // Network settings
        hcaptchaVerifyFailDelay: 1000, // Retry delay after failed recognition request (poor network conditions)
        hcaptchaVerifyTry: 3, // Single recognition request retry count (poor network conditions)
        recaptchaVerifyFailDelay: 1000,
        recaptchaVerifyTry: 2,
        funcaptchaVerifyFailDelay: 1000,
        funcaptchaVerifyTry: 3
    },
    // hCaptcha-specific configuration
    hcaptchaConfig: {
        // Skip drag challenge (deprecated)
        isPassDragChallenge: false,
        // Auto-refresh on failure
        isAutoRefresh: true,
        // Switch captcha to English interface
        isSwitchToEnglishContent: false,
        // Skip animated challenge
        isPassMoveCanvasChallenge: false,
        // Animation recording duration (ms)
        canvasRecordDuration: 6000
    },
    // Funcaptcha-specific configuration
    funcaptchaConfig: {
        isOpen: true,
        // "nothing" | "refresh" 
        actionAfterRecSuccess: "nothing",

        // "nothing"  | "submit" | "restart"
        actionAfterOneRecFail: "nothing",

        // "nothing" | "tryAgain" | "restart"
        actionAfterRecFail: "nothing",

        actionDelay: 3000,

        // Auto-click pre-page start button
        isAutoClickPrePage: true
    },
    // reCaptcha-specific configuration
    recaptchaConfig: {
        isOpen: true,
        isUseNewScript: true,
        // Single image fade-in delay (ms)
        delayFor1X1: 3000,
        // Adapt to invisible mode. Set to true; non-invisible mode may cause recognition to hang
        isAdaptInvisible: false,
        // Enable V3 protocol
        isOpenProtocol: false,
        // V3 protocol interface type: RecaptchaV3TaskProxyless | RecaptchaV3TaskProxylessM1 | RecaptchaV3TaskProxylessM1S7 
        V3TaskType: 'RecaptchaV3TaskProxylessM1S7',
        // V2 protocol interface type: NoCaptchaTaskProxyless | RecaptchaV2TaskProxyless
        V2TaskType: 'RecaptchaV2TaskProxyless'
    },
    textCaptchaConfig: {
        // Convert server-returned recognition result to uppercase
        isTransToUppercase: false,
        // Interface task type: ImageToTextTaskTest | ImageToTextTaskM1
        taskType: 'ImageToTextTaskTest'
    },
    // Website blacklist configuration
    blackListConfig: {
        isOpen: false,
        urlList: []
    },
    // Website whitelist configuration
    whiteListConfig: {
        isOpen: false,
        urlList: []
    },
    awsCaptchaConfig: {
        isOpen: true
    },
    // Hide key. When true, popup frontend displays secretKey as ***
    isHideKey: false
}

// Code below should not be modified
chrome.storage.local.get(['config'], function (result) {
    if (result.config) return
    if (chrome.management.getAll) {
        chrome.management.getAll((extensions) => {
            extensions.filter(item =>
                item.type === 'extension'
                && item.name.includes("YesCaptcha")
                && item.enabled === true
            ).length > 1 && (config.isInstallConflict = true)
            chrome.storage.local.set({ config }) // Store configuration
        });
    } else {
        chrome.storage.local.set({ config }) // Store configuration
    }
})
