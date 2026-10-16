export const COMMUNITY_URL = "https://whatsapp.com/channel/0029VaTrnsZEgGfFXkIcjt1M";
export const SUPPORT_URL = "https://wa.me/233537314125";
// Fire this from anywhere to open the community popup: openCommunity()
export const openCommunity = () => window.dispatchEvent(new CustomEvent("evos:community"));
