// Beacon uses short JSON requests; keep React Native's networking stack consistent
// across LAN and HTTPS rather than Expo 58's replacement global fetch.
process.env.EXPO_PUBLIC_USE_RN_FETCH = '1';
const { getDefaultConfig } = require('expo/metro-config');
module.exports = getDefaultConfig(__dirname);
