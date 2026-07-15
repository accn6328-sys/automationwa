import makeWASocket, { useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason } from '@whiskeysockets/baileys';
import pino from 'pino';
import express from 'express';
import http from 'http';
import { Server } from 'socket.io';
import QRCode from 'qrcode';
import fs from 'fs';
import path from 'path';
import cors from 'cors';
import { fileURLToPath } from 'url';
import { exec, spawn, execSync } from 'child_process';
import { promisify } from 'util';
import ffmpegPath from 'ffmpeg-static';
import { createProxyMiddleware } from 'http-proxy-middleware';
import os from 'os';

const execPromise = promisify(exec);

// Manual .env file loader for workspace root fallbacks
const envPaths = [
    path.resolve(__dirname, '..', '.env'),
    path.resolve(__dirname, '..', '..', '.env'),
    path.resolve(__dirname, '.env')
];
for (const envPath of envPaths) {
    if (fs.existsSync(envPath)) {
        try {
            const content = fs.readFileSync(envPath, 'utf8');
            content.split('\n').forEach(line => {
                line = line.trim();
                if (line && !line.startsWith('#') && line.includes('=')) {
                    const parts = line.split('=');
                    const k = parts[0].trim();
                    const v = parts.slice(1).join('=').trim().replace(/^['"]|['"]$/g, '');
                    if (k && !process.env[k]) {
                        process.env[k] = v;
                    }
                }
            });
            console.log(`[Env Loader] Loaded .env variables from ${envPath}`);
        } catch (err) {
            console.error(`[Env Loader] Error reading ${envPath}:`, err.message);
        }
    }
}

// Global cached Shopify token logic
let cachedShopifyToken = null;
let cachedShopifyTokenExpires = 0;

async function getShopifyAccessToken() {
    if (cachedShopifyToken && Date.now() < cachedShopifyTokenExpires - 60000) {
        return cachedShopifyToken;
    }
    const storeDomain = process.env.SHOPIFY_STORE_DOMAIN || '2txc0h-0a.myshopify.com';
    const cleanDomain = storeDomain.replace(/^https?:\/\//, '').trim();
    const clientId = process.env.SHOPIFY_CLIENT_ID;
    const clientSecret = process.env.SHOPIFY_APP_SECRET;
    
    if (clientId && clientSecret) {
        try {
            console.log(`[Shopify OAuth] Requesting access token for ${cleanDomain}...`);
            const resp = await fetch(`https://${cleanDomain}/admin/oauth/access_token`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: new URLSearchParams({
                    grant_type: 'client_credentials',
                    client_id: clientId,
                    client_secret: clientSecret
                }),
                signal: AbortSignal.timeout(10000)
            });
            if (resp.ok) {
                const data = await resp.json();
                cachedShopifyToken = data.access_token;
                cachedShopifyTokenExpires = Date.now() + (data.expires_in || 86399) * 1000;
                console.log('[Shopify OAuth] Successfully obtained access token.');
                return cachedShopifyToken;
            } else {
                console.log(`[Shopify OAuth] Token exchange failed with status ${resp.status}: ${await resp.text()}`);
            }
        } catch (e) {
            console.log(`[Shopify OAuth] Token exchange exception: ${e.message}`);
        }
    }
    
    // Fallback to static token
    return process.env.SHOPIFY_ADMIN_TOKEN;
}

// Session backup/restore helpers
// Saves auth_info_baileys as base64 JSON to a backup file so sessions survive Railway restarts
const SESSION_BACKUP_PATH = process.env.SESSION_BACKUP_PATH || path.join(os.tmpdir(), 'wa_session_backup.json');

function backupSession(authDir) {
    try {
        if (!fs.existsSync(authDir)) return;
        const files = {};
        fs.readdirSync(authDir).forEach(f => {
            files[f] = fs.readFileSync(path.join(authDir, f), 'base64');
        });
        fs.writeFileSync(SESSION_BACKUP_PATH, JSON.stringify(files));
    } catch(e) { console.error('Session backup failed:', e.message); }
}

function restoreSession(authDir) {
    try {
        if (!fs.existsSync(SESSION_BACKUP_PATH)) return false;
        if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
        const files = JSON.parse(fs.readFileSync(SESSION_BACKUP_PATH, 'utf8'));
        Object.entries(files).forEach(([name, b64]) => {
            fs.writeFileSync(path.join(authDir, name), Buffer.from(b64, 'base64'));
        });
        console.log('[Session] Restored session from backup.');
        return true;
    } catch(e) { console.error('Session restore failed:', e.message); return false; }
}

// Resolve __dirname in ES module context
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Official WhatsApp Cloud API Helpers
async function uploadWAMedia(phoneId, token, base64Data, filename, mimeType) {
    const url = `https://graph.facebook.com/v19.0/${phoneId}/media`;
    const cleanB64 = base64Data.split(',')[1] || base64Data;
    const blob = new Blob([Buffer.from(cleanB64, 'base64')], { type: mimeType });
    const form = new FormData();
    form.append('file', blob, filename);
    form.append('messaging_product', 'whatsapp');
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${token}`
        },
        body: form
    });
    if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Media upload failed: ${errText}`);
    }
    const resData = await response.json();
    return resData.id;
}

async function sendOfficialWAMessage(phoneId, token, number, text, image, voice) {
    const url = `https://graph.facebook.com/v19.0/${phoneId}/messages`;
    const cleanTo = number.replace(/\D/g, '');
    const payload = {
        messaging_product: 'whatsapp',
        recipient_type: 'individual',
        to: cleanTo
    };
    if (image && typeof image === 'string' && image.length > 100) {
        let mimeType = 'image/jpeg';
        let ext = 'jpg';
        const mimeMatch = image.match(/^data:([^;]+);base64,/);
        if (mimeMatch) {
            mimeType = mimeMatch[1];
            ext = mimeType.split('/')[1] || 'jpg';
        }
        const mediaId = await uploadWAMedia(phoneId, token, image, `file_${Date.now()}.${ext}`, mimeType);
        payload.type = 'image';
        payload.image = { id: mediaId };
        if (text) payload.image.caption = text;
    } else if (voice && typeof voice === 'string' && voice.length > 100) {
        const { filePath } = await convertToOggOpusFile(voice);
        const dataBuffer = fs.readFileSync(filePath);
        const base64Ogg = dataBuffer.toString('base64');
        try { fs.unlinkSync(filePath); } catch (e) {}

        const mediaId = await uploadWAMedia(phoneId, token, base64Ogg, `audio_${Date.now()}.ogg`, 'audio/ogg; codecs=opus');
        payload.type = 'audio';
        payload.audio = { id: mediaId };
        
        const response1 = await fetch(url, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        if (!response1.ok) {
            const errText = await response1.text();
            throw new Error(`Audio delivery failed: ${errText}`);
        }
        
        if (text) {
            const textPayload = {
                messaging_product: 'whatsapp',
                recipient_type: 'individual',
                to: cleanTo,
                type: 'text',
                text: { body: text, preview_url: true }
            };
            const response2 = await fetch(url, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(textPayload)
            });
            if (!response2.ok) {
                const errText = await response2.text();
                throw new Error(`Separated text delivery failed: ${errText}`);
            }
        }
        return await response1.json();
    } else {
        payload.type = 'text';
        payload.text = { body: text, preview_url: true };
    }
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    });
    if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Message delivery failed: ${errText}`);
    }
    return await response.json();
}

// Helper function to transcode audio to strict OGG/Opus format using FFmpeg and return the file path
async function convertToOggOpusFile(base64Data) {
    const tempDir = path.join(__dirname, 'temp_audio');
    if (!fs.existsSync(tempDir)) {
        fs.mkdirSync(tempDir, { recursive: true });
    }
    
    const randomId = Math.random().toString(36).substring(7);
    const inputPath = path.join(tempDir, `input_${randomId}.webm`);
    const outputPath = path.join(tempDir, `output_${randomId}.ogg`);
    
    // Ensure executable permissions on non-Windows
    if (process.platform !== 'win32') {
        try {
            fs.chmodSync(ffmpegPath, 0o755);
        } catch (e) {
            console.error('Failed to chmod ffmpeg-static:', e);
        }
    }
    
    try {
        const buffer = Buffer.from(base64Data.split(',')[1] || base64Data, 'base64');
        fs.writeFileSync(inputPath, buffer);
        
        // Transcode WebM/MP4 audio to Mono, 48kHz, Opus codec OGG container for WhatsApp compatibility
        // Try libopus first
        let command = `"${ffmpegPath}" -y -i "${inputPath}" -vn -c:a libopus -b:a 16k -ar 16000 -ac 1 -avoid_negative_ts make_zero -f ogg "${outputPath}"`;
        try {
            await execPromise(command);
        } catch (err) {
            addLog(`[FFmpeg libopus failed, trying native opus] ${err.message}`);
            // Fallback to native opus encoder
            command = `"${ffmpegPath}" -y -i "${inputPath}" -vn -c:a opus -b:a 16k -ar 16000 -ac 1 -avoid_negative_ts make_zero -f ogg "${outputPath}"`;
            await execPromise(command);
        }
        
        if (fs.existsSync(inputPath)) {
            try { fs.unlinkSync(inputPath); } catch (e) {}
        }
        
        return { filePath: outputPath, isTranscoded: true };
    } catch (err) {
        addLog(`[FFmpeg transcoding failed completely] ${err.message}`);
        // Fallback: write raw webm to temporary file and return it
        const fallbackPath = path.join(tempDir, `fallback_${randomId}.webm`);
        try {
            const buffer = Buffer.from(base64Data.split(',')[1] || base64Data, 'base64');
            fs.writeFileSync(fallbackPath, buffer);
        } catch (writeErr) {
            addLog(`[FFmpeg fallback write failed] ${writeErr.message}`);
        }
        
        // Cleanup input and output
        if (fs.existsSync(inputPath)) { try { fs.unlinkSync(inputPath); } catch (e) {} }
        if (fs.existsSync(outputPath)) { try { fs.unlinkSync(outputPath); } catch (e) {} }
        
        return { filePath: fallbackPath, isTranscoded: false };
    }
}

// Helper to match keywords as whole words or exact phrases (preventing loose substring matching)
function matchKeyword(messageText, keyword) {
    const msg = messageText.trim().toLowerCase();
    const kw = keyword.trim().toLowerCase();
    
    if (msg === kw) return true;
    
    let pattern = '';
    if (/^\w/.test(kw)) pattern += '\\b';
    pattern += kw.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
    if (/\w$/.test(kw)) pattern += '\\b';
    
    try {
        const regex = new RegExp(pattern, 'i');
        return regex.test(msg);
    } catch (e) {
        return msg.includes(kw);
    }
}

// Initialize logs container
const logs = [];
function addLog(text) {
    const time = new Date().toLocaleTimeString();
    const logItem = { time, text };
    logs.push(logItem);
    if (logs.length > 200) logs.shift();
    if (io) {
        io.emit('log', logItem);
    }
    console.log(`[${time}] ${text}`);
}

// Keyword handlers
// Allow overriding the keywords file path via env var (useful for Railway persistent volumes)
const isRailway = !!(process.env.RAILWAY_ENVIRONMENT || process.env.RAILWAY_SERVICE_ID);

// Detect persistent volume directory (e.g. /data on Railway)
let persistentDir = process.env.PERSISTENT_DIR;
if (!persistentDir && fs.existsSync('/data')) {
    persistentDir = '/data';
}

const AUTH_DIR = process.env.AUTH_DIR || (persistentDir ? path.join(persistentDir, 'auth_info_baileys') : (isRailway ? path.join(__dirname, 'auth_info_baileys') : path.join(__dirname, '..', 'auth_info_baileys')));

// Ensure persistent storage directory exists
if (!fs.existsSync(AUTH_DIR)) {
    try {
        fs.mkdirSync(AUTH_DIR, { recursive: true });
    } catch (e) {
        console.error('Failed to create AUTH_DIR:', e);
    }
}

const KEYWORDS_PATH = process.env.KEYWORDS_PATH || (persistentDir ? path.join(persistentDir, 'keywords.json') : (isRailway ? path.join(__dirname, 'keywords.json') : path.join(__dirname, '..', 'keywords.json')));
const CONTACTS_FILE = process.env.CONTACTS_FILE || (persistentDir ? path.join(persistentDir, 'active_contacts.json') : (isRailway ? path.join(__dirname, 'active_contacts.json') : path.join(__dirname, '..', 'active_contacts.json')));
const CONV_STATE_PATH = process.env.CONV_STATE_PATH || (persistentDir ? path.join(persistentDir, 'conversation_state.json') : (isRailway ? path.join(__dirname, 'conversation_state.json') : path.join(__dirname, '..', 'conversation_state.json')));
const ORDER_FLOW_CONFIG_PATH = process.env.ORDER_FLOW_CONFIG_PATH || (persistentDir ? path.join(persistentDir, 'order_flow_config.json') : (isRailway ? path.join(__dirname, 'order_flow_config.json') : path.join(__dirname, '..', 'order_flow_config.json')));
const ORDERS_PATH = process.env.ORDERS_PATH || (persistentDir ? path.join(persistentDir, 'orders.json') : (isRailway ? path.join(__dirname, 'orders.json') : path.join(__dirname, '..', 'orders.json')));

// Initialize persistent keywords file if not present, copying from default template
const DEFAULT_KEYWORDS_PATH = path.join(__dirname, 'keywords.json');
if (!fs.existsSync(KEYWORDS_PATH)) {
    try {
        if (KEYWORDS_PATH !== DEFAULT_KEYWORDS_PATH && fs.existsSync(DEFAULT_KEYWORDS_PATH)) {
            fs.copyFileSync(DEFAULT_KEYWORDS_PATH, KEYWORDS_PATH);
            console.log('[Setup] Copied default keywords template to persistent storage.');
        } else {
            fs.writeFileSync(KEYWORDS_PATH, '{}', 'utf8');
        }
    } catch (e) {
        console.error('Failed to initialize persistent keywords.json:', e);
    }
}

// Ensure persistent contacts file exists
if (!fs.existsSync(CONTACTS_FILE)) {
    try {
        fs.writeFileSync(CONTACTS_FILE, '[]', 'utf8');
    } catch (e) {
        console.error('Failed to initialize active_contacts.json:', e);
    }
}

// Ensure persistent conversation state file exists
if (!fs.existsSync(CONV_STATE_PATH)) {
    try {
        fs.writeFileSync(CONV_STATE_PATH, '{}', 'utf8');
    } catch (e) {
        console.error('Failed to initialize conversation_state.json:', e);
    }
}

// Ensure persistent order flow config file exists
const defaultOrderFlowConfig = {
    "enabled": true,
    "payment_link": "https://your-payment-link-here.com",
    "cod_label": "Cash on Delivery",
    "online_label": "Online Payment",
    "questions": [
        { "key": "name", "prompt": "What's your full name?" },
        { "key": "address", "prompt": "What's your full delivery address?" },
        { "key": "pincode", "prompt": "What's your PIN code?" },
        { "key": "phone", "prompt": "What's the best phone number to reach you on?" }
    ],
    "cod_confirmation_template": "Thanks {name}! Your Cash on Delivery order is confirmed.\nAddress: {address}\nPIN: {pincode}\nPhone: {phone}\nWe'll contact you soon to confirm delivery.",
    "online_confirmation_template": "Thanks {name}! Please complete payment here: {payment_link}\nOnce paid, we'll ship to:\nAddress: {address}\nPIN: {pincode}\nPhone: {phone}"
};

if (!fs.existsSync(ORDER_FLOW_CONFIG_PATH)) {
    try {
        fs.writeFileSync(ORDER_FLOW_CONFIG_PATH, JSON.stringify(defaultOrderFlowConfig, null, 2), 'utf8');
    } catch (e) {
        console.error('Failed to initialize order_flow_config.json:', e);
    }
}

// Ensure persistent orders file exists
if (!fs.existsSync(ORDERS_PATH)) {
    try {
        fs.writeFileSync(ORDERS_PATH, '[]', 'utf8');
    } catch (e) {
        console.error('Failed to initialize orders.json:', e);
    }
}

function loadKeywords() {
    try {
        if (fs.existsSync(KEYWORDS_PATH)) {
            return JSON.parse(fs.readFileSync(KEYWORDS_PATH, 'utf8'));
        }
    } catch (e) {
        addLog(`Error loading keywords: ${e.message}`);
    }
    return {};
}

function saveKeywords(kwMap) {
    try {
        fs.writeFileSync(KEYWORDS_PATH, JSON.stringify(kwMap, null, 2), 'utf8');
        return true;
    } catch (e) {
        addLog(`Error saving keywords: ${e.message}`);
        return false;
    }
}

function loadConvState() {
    try {
        if (fs.existsSync(CONV_STATE_PATH)) {
            const data = JSON.parse(fs.readFileSync(CONV_STATE_PATH, 'utf8'));
            const now = Date.now();
            const oneDayMs = 24 * 60 * 60 * 1000;
            let updated = false;
            for (const jid of Object.keys(data)) {
                const entry = data[jid];
                if (entry && (!entry.updatedAt || now - entry.updatedAt > oneDayMs)) {
                    delete data[jid];
                    updated = true;
                }
            }
            if (updated) {
                fs.writeFileSync(CONV_STATE_PATH, JSON.stringify(data, null, 2), 'utf8');
            }
            return data;
        }
    } catch (e) {
        addLog(`Error loading conversation state: ${e.message}`);
    }
    return {};
}

function saveConvState(state) {
    try {
        fs.writeFileSync(CONV_STATE_PATH, JSON.stringify(state, null, 2), 'utf8');
        return true;
    } catch (e) {
        addLog(`Error saving conversation state: ${e.message}`);
        return false;
    }
}

function clearConvState(jid) {
    const state = loadConvState();
    if (state[jid]) {
        delete state[jid];
        saveConvState(state);
    }
}

function loadOrderFlowConfig() {
    try {
        if (fs.existsSync(ORDER_FLOW_CONFIG_PATH)) {
            return JSON.parse(fs.readFileSync(ORDER_FLOW_CONFIG_PATH, 'utf8'));
        }
    } catch (e) {
        addLog(`Error loading order flow config: ${e.message}`);
    }
    return defaultOrderFlowConfig;
}

function saveOrderFlowConfig(config) {
    try {
        fs.writeFileSync(ORDER_FLOW_CONFIG_PATH, JSON.stringify(config, null, 2), 'utf8');
        return true;
    } catch (e) {
        addLog(`Error saving order flow config: ${e.message}`);
        return false;
    }
}

function loadOrders() {
    try {
        if (fs.existsSync(ORDERS_PATH)) {
            const data = JSON.parse(fs.readFileSync(ORDERS_PATH, 'utf8'));
            if (Array.isArray(data)) return data;
        }
    } catch (e) {
        addLog(`Error loading orders: ${e.message}`);
    }
    return [];
}

function saveOrders(orders) {
    try {
        fs.writeFileSync(ORDERS_PATH, JSON.stringify(orders, null, 2), 'utf8');
        return true;
    } catch (e) {
        addLog(`Error saving orders: ${e.message}`);
        return false;
    }
}

// ── Shopify Admin REST API Order Creator Integration ──
function extractField(answers, possibleKeys) {
    for (const key of possibleKeys) {
        const lowerKey = key.toLowerCase();
        for (const [ansKey, ansVal] of Object.entries(answers)) {
            const lowerAnsKey = ansKey.toLowerCase();
            if (lowerAnsKey === lowerKey || lowerAnsKey.includes(lowerKey)) {
                if (ansVal && ansVal.toString().trim().length > 0) {
                    return ansVal.toString().trim();
                }
            }
        }
    }
    return null;
}

async function createShopifyOrderForState(userState, senderJid, senderName, sock) {
    const answers = userState.answers || {};
    
    // Extract fields dynamically from collected answers
    const name = extractField(answers, ['name', 'customer', 'full name', 'buyer']) || senderName || 'WhatsApp Customer';
    let phone = extractField(answers, ['phone', 'mobile', 'contact', 'number']);
    if (!phone && senderJid) {
        phone = senderJid.split('@')[0];
    }
    const address = extractField(answers, ['address', 'shipping', 'location', 'delivery']);
    const pincode = extractField(answers, ['pincode', 'pin', 'zip', 'zipcode', 'area code', 'postal']);
    const variantId = extractField(answers, ['variant', 'product', 'id', 'item_id', 'variant_id']);
    const quantityStr = extractField(answers, ['quantity', 'qty', 'count', 'number of items']) || '1';
    const priceStr = extractField(answers, ['price', 'amount', 'cost', 'rate']);
    
    // Validate required fields: address, phone, product ID (variant ID)
    const missingFields = [];
    if (!phone) missingFields.push('phone');
    if (!address) missingFields.push('address');
    if (!variantId) missingFields.push('product variant ID');
    
    if (missingFields.length > 0) {
        const errMsg = `Shopify order failed: Missing required fields (${missingFields.join(', ')}).`;
        addLog(`[Shopify Error] ${errMsg}`);
        
        // Log payload and error to failed_orders.log
        const logPayload = {
            timestamp: new Date().toISOString(),
            error: errMsg,
            answers: answers,
            senderJid: senderJid,
            senderName: senderName
        };
        fs.appendFileSync(
            path.join(__dirname, 'failed_orders.log'),
            JSON.stringify(logPayload, null, 2) + '\n\n',
            'utf8'
        );
        
        // Alert admin via WhatsApp
        try {
            const adminJid = '916282444918@s.whatsapp.net';
            await sock.sendMessage(adminJid, {
                text: `⚠️ *Shopify Order Creation Failed!*\n\n` +
                      `*Error*: ${errMsg}\n` +
                      `*Customer*: ${senderName} (${senderJid.split('@')[0]})\n` +
                      `*Answers*:\n${JSON.stringify(answers, null, 2)}`
            });
        } catch(e) {
            addLog(`Failed to alert admin: ${e.message}`);
        }
        return;
    }
    
    const quantity = parseInt(quantityStr, 10) || 1;
    const price = priceStr ? parseFloat(priceStr) : null;
    
    // COD is set to financial_status "pending"; online is set to "paid"
    const financialStatus = userState.paymentMethod === 'cod' ? 'pending' : 'paid';
    
    const shopifyOrder = {
        order: {
            line_items: [
                {
                    variant_id: parseInt(variantId, 10),
                    quantity: quantity
                }
            ],
            customer: {
                first_name: name,
                phone: phone
            },
            shipping_address: {
                first_name: name,
                address1: address,
                phone: phone,
                zip: pincode || "",
                country: "India"
            },
            financial_status: financialStatus,
            phone: phone
        }
    };
    
    if (price !== null && !isNaN(price)) {
        shopifyOrder.order.line_items[0].price = price;
    }
    
    const storeDomain = process.env.SHOPIFY_STORE_DOMAIN;
    const adminToken = await getShopifyAccessToken();
    
    if (!storeDomain || !adminToken || adminToken.includes('xxxxxx')) {
        const errMsg = 'Shopify credentials missing or unconfigured in .env file.';
        addLog(`[Shopify Error] ${errMsg}`);
        
        fs.appendFileSync(
            path.join(__dirname, 'failed_orders.log'),
            JSON.stringify({ timestamp: new Date().toISOString(), error: errMsg, payload: shopifyOrder }, null, 2) + '\n\n',
            'utf8'
        );
        
        try {
            const adminJid = '916282444918@s.whatsapp.net';
            await sock.sendMessage(adminJid, {
                text: `⚠️ *Shopify Order Creation Failed!*\n\n` +
                      `*Error*: ${errMsg}\n` +
                      `*Customer*: ${senderName} (${senderJid.split('@')[0]})`
            });
        } catch(e) {}
        return;
    }
    
    let cleanDomain = storeDomain.replace('https://', '').replace('http://', '').trim();
    if (!cleanDomain.endsWith('.myshopify.com') && !cleanDomain.includes('.')) {
        cleanDomain = `${cleanDomain}.myshopify.com`;
    }
    
    const shopifyUrl = `https://${cleanDomain}/admin/api/2025-01/orders.json`;
    
    try {
        const response = await fetch(shopifyUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Shopify-Access-Token': adminToken
            },
            body: JSON.stringify(shopifyOrder)
        });
        
        const data = await response.json();
        
        if (response.ok && data.order) {
            const orderNumber = data.order.order_number || data.order.name || data.order.id;
            addLog(`Shopify Order created successfully: #${orderNumber}`);
            
            // Send confirmation back to customer via WhatsApp
            const confirmationMsg = `🎉 *Order Confirmed!*\n\n` +
                                    `Thank you for ordering, *${name}*! Your order has been placed successfully.\n` +
                                    `🛍️ *Shopify Order ID*: #${orderNumber}\n` +
                                    `We will update you once your order is dispatched.`;
            await sock.sendMessage(senderJid, { text: confirmationMsg });
        } else {
            const errDetails = data.errors ? JSON.stringify(data.errors) : JSON.stringify(data);
            throw new Error(`Shopify API responded with status ${response.status}: ${errDetails}`);
        }
    } catch(err) {
        addLog(`[Shopify Error] Shopify API request failed: ${err.message}`);
        
        const failedPayload = {
            timestamp: new Date().toISOString(),
            error: err.message,
            payload: shopifyOrder
        };
        fs.appendFileSync(
            path.join(__dirname, 'failed_orders.log'),
            JSON.stringify(failedPayload, null, 2) + '\n\n',
            'utf8'
        );
        
        // Notify admin via WhatsApp
        try {
            const adminJid = '916282444918@s.whatsapp.net';
            await sock.sendMessage(adminJid, {
                text: `⚠️ *Shopify Order Creation Failed!*\n\n` +
                      `*Error*: ${err.message}\n` +
                      `*Customer*: ${senderName} (${senderJid.split('@')[0]})`
            });
        } catch(e) {}
    }
}

function loadActiveContacts() {
    try {
        if (fs.existsSync(CONTACTS_FILE)) {
            const list = JSON.parse(fs.readFileSync(CONTACTS_FILE, 'utf8'));
            if (Array.isArray(list)) return list;
        }
    } catch (e) {
        console.error('Error loading active contacts:', e.message);
    }
    return [];
}

function saveActiveContacts(contacts) {
    try {
        fs.writeFileSync(CONTACTS_FILE, JSON.stringify(contacts, null, 2), 'utf8');
        return true;
    } catch (e) {
        console.error('Error saving active contacts:', e.message);
        return false;
    }
}

function addContact(jid) {
    if (!jid || !jid.endsWith('@s.whatsapp.net')) return;
    const contacts = loadActiveContacts();
    if (!contacts.includes(jid)) {
        contacts.push(jid);
        saveActiveContacts(contacts);
        addLog(`[Contact Sync] Added new active contact: ${jid}`);
    }
}

// Clears Baileys credentials and token state files, keeping rules and contacts intact
function clearSessionFiles(dir) {
    if (!fs.existsSync(dir)) return;
    try {
        fs.readdirSync(dir).forEach(f => {
            if (f !== 'keywords.json' && f !== 'active_contacts.json') {
                const filePath = path.join(dir, f);
                try {
                    const stat = fs.statSync(filePath);
                    if (stat.isDirectory()) {
                        fs.rmSync(filePath, { recursive: true, force: true });
                    } else {
                        fs.unlinkSync(filePath);
                    }
                } catch (e) {
                    console.error(`Failed to delete session file ${f}:`, e.message);
                }
            }
        });
        addLog('Session credentials cleared (rules & active contacts preserved).');
    } catch (e) {
        addLog(`Error during session cleanup: ${e.message}`);
    }
}

// ── YT Bot subprocess launcher ──────────────────────────────────────────────
// The Python Flask YT bot runs on internal port 8080, proxied at /yt/*
const PORT = process.env.PORT || 3000;
// Swap YT bot and Express ports if PORT is 8080 (Railway default target port)
// so that Express runs on 8081 (where Railway routes traffic) and YT bot runs on 8080 internally.
const EXPRESS_PORT = PORT == 8080 ? 8081 : PORT;
const YT_BOT_PORT = PORT == 8080 ? 8080 : parseInt(PORT) + 1;
const FB_BOT_PORT = parseInt(PORT) + 2;

const YT_BOT_DIR = path.join(__dirname, 'yt-bot');
let ytBotProcess = null;

const FB_BOT_DIR = path.join(__dirname, 'fb-bot');
let fbBotProcess = null;

function findPythonBinary() {
    if (process.platform === 'win32') return 'python';
    
    // Dynamically append Nix profile bins to PATH so subprocesses can resolve Nix packages
    const nixBins = [
        '/root/.nix-profile/bin',
        '/home/nixpacks/.nix-profile/bin',
        '/nix/var/nix/profiles/default/bin'
    ];
    process.env.PATH = `${process.env.PATH}:${nixBins.join(':')}`;
    addLog(`[YT Debug] Extended PATH: ${process.env.PATH}`);

    try {
        const binSearch = execSync('which -a python python3 python3.11 python3.10 python3.9 python3.8 python3.7 2>&1 || true').toString().trim();
        addLog(`[YT Debug] 'which' search results:\n${binSearch}`);
    } catch (e) {}
    
    try {
        const binList = execSync('ls -la /usr/bin/python* /usr/local/bin/python* /root/.nix-profile/bin/python* /home/nixpacks/.nix-profile/bin/python* 2>/dev/null || true').toString().trim();
        if (binList) addLog(`[YT Debug] ls -la output:\n${binList}`);
    } catch (e) {}

    const candidates = ['python3', 'python', 'python3.11', 'python3.10', 'python3.9'];
    for (const name of candidates) {
        try {
            const binPath = execSync(`which ${name}`, { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim();
            if (binPath && fs.existsSync(binPath)) return binPath;
        } catch (e) {}
    }
    
    const commonPaths = [
        '/usr/bin/python3',
        '/usr/bin/python',
        '/usr/local/bin/python3',
        '/usr/local/bin/python',
        '/root/.nix-profile/bin/python3',
        '/root/.nix-profile/bin/python',
        '/home/nixpacks/.nix-profile/bin/python3',
        '/home/nixpacks/.nix-profile/bin/python'
    ];
    for (const p of commonPaths) {
        if (fs.existsSync(p)) return p;
    }
    return 'python3';
}

function startYTBot() {
    const ytAppPath = path.join(YT_BOT_DIR, 'app.py');
    if (!fs.existsSync(ytAppPath)) {
        console.log('[YT Bot] yt-bot/app.py not found — skipping YT bot startup.');
        return;
    }

    const pythonBin = findPythonBinary();
    console.log(`[YT Bot] Using python executable: ${pythonBin}`);
    addLog(`[YT Bot] Found python binary: ${pythonBin}`);
    console.log('[YT Bot] Starting Python Flask YT bot on internal port', YT_BOT_PORT);
    
    const ytProc = spawn(pythonBin, ['app.py'], {
        stdio: 'pipe',
        cwd: YT_BOT_DIR,
        env: { ...process.env, FLASK_PORT: String(YT_BOT_PORT) }
    });
    
    let ytErrorBuffer = [];
    
    ytProc.stdout.on('data', d => {
        const text = d.toString().trim();
        if (text) {
            console.log(`[YT Bot] ${text}`);
            if (text.includes('[LAUNCH]') || text.includes('Running')) {
                addLog(`[YT Bot] ${text}`);
            }
        }
    });
    
    ytProc.stderr.on('data', d => {
        const text = d.toString().trim();
        if (text) {
            console.error(`[YT Bot] ${text}`);
            ytErrorBuffer.push(text);
            if (ytErrorBuffer.length > 30) ytErrorBuffer.shift();
        }
    });
    
    ytProc.on('close', code => {
        addLog(`❌ [YT Bot] Subprocess exited with code ${code}.`);
        if (ytErrorBuffer.length > 0) {
            addLog(`❌ [YT Bot] Crash logs:`);
            ytErrorBuffer.forEach(line => addLog(`   👉 ${line}`));
        }
        addLog(`[YT Bot] Restarting in 5 seconds...`);
        ytBotProcess = null;
        setTimeout(startYTBot, 5000);
    });
    
    ytProc.on('error', err => {
        addLog(`❌ [YT Bot] Spawn error: ${err.message}`);
    });
    
    ytBotProcess = ytProc;
}

function startFBBot() {
    const fbAppPath = path.join(FB_BOT_DIR, 'app.py');
    if (!fs.existsSync(fbAppPath)) {
        console.log('[FB Bot] fb-bot/app.py not found — skipping FB bot startup.');
        return;
    }

    const pythonBin = findPythonBinary();
    console.log(`[FB Bot] Using python executable: ${pythonBin}`);
    addLog(`[FB Bot] Found python binary: ${pythonBin}`);
    console.log('[FB Bot] Starting Python Flask FB bot on internal port', FB_BOT_PORT);
    
    const fbProc = spawn(pythonBin, ['app.py'], {
        stdio: 'pipe',
        cwd: FB_BOT_DIR,
        env: { ...process.env, FLASK_PORT: String(FB_BOT_PORT) }
    });
    
    let fbErrorBuffer = [];
    
    fbProc.stdout.on('data', d => {
        const text = d.toString().trim();
        if (text) {
            console.log(`[FB Bot] ${text}`);
            if (text.includes('[LAUNCH]') || text.includes('Running')) {
                addLog(`[FB Bot] ${text}`);
            }
        }
    });
    
    fbProc.stderr.on('data', d => {
        const text = d.toString().trim();
        if (text) {
            console.error(`[FB Bot] ${text}`);
            fbErrorBuffer.push(text);
            if (fbErrorBuffer.length > 30) fbErrorBuffer.shift();
        }
    });
    
    fbProc.on('close', code => {
        addLog(`❌ [FB Bot] Subprocess exited with code ${code}.`);
        if (fbErrorBuffer.length > 0) {
            addLog(`❌ [FB Bot] Crash logs:`);
            fbErrorBuffer.forEach(line => addLog(`   👉 ${line}`));
        }
        addLog(`[FB Bot] Restarting in 5 seconds...`);
        fbBotProcess = null;
        setTimeout(startFBBot, 5000);
    });
    
    fbProc.on('error', err => {
        addLog(`❌ [FB Bot] Spawn error: ${err.message}`);
    });
    
    fbBotProcess = fbProc;
}

let reposterProcess = null;
function startReposterDaemon() {
    const reposterPath = path.join(__dirname, 'reposter_daemon.py');
    if (!fs.existsSync(reposterPath)) {
        console.log('[Reposter Bot] reposter_daemon.py not found — skipping startup.');
        return;
    }

    const pythonBin = findPythonBinary();
    console.log(`[Reposter Bot] Using python executable: ${pythonBin}`);
    addLog(`[Reposter Bot] Starting Instagram-to-YouTube reposter daemon...`);
    
    const repProc = spawn(pythonBin, ['reposter_daemon.py'], {
        stdio: 'pipe',
        cwd: __dirname,
        env: { ...process.env }
    });
    
    let repErrorBuffer = [];
    
    repProc.stdout.on('data', d => {
        const text = d.toString().trim();
        if (text) {
            console.log(`[Reposter Bot] ${text}`);
            addLog(`[Reposter Bot] ${text}`);
        }
    });
    
    repProc.stderr.on('data', d => {
        const text = d.toString().trim();
        if (text) {
            console.error(`[Reposter Bot] ${text}`);
            repErrorBuffer.push(text);
            if (repErrorBuffer.length > 30) repErrorBuffer.shift();
        }
    });
    
    repProc.on('close', code => {
        addLog(`❌ [Reposter Bot] Subprocess exited with code ${code}.`);
        if (repErrorBuffer.length > 0) {
            addLog(`❌ [Reposter Bot] Crash logs:`);
            repErrorBuffer.forEach(line => addLog(`   👉 ${line}`));
        }
        addLog(`[Reposter Bot] Restarting in 10 seconds...`);
        reposterProcess = null;
        setTimeout(startReposterDaemon, 10000);
    });
    
    repProc.on('error', err => {
        addLog(`❌ [Reposter Bot] Spawn error: ${err.message}`);
    });
    
    reposterProcess = repProc;
}

function getPaymentInstructionText(lang, price, plUrl) {
    const langLower = (lang || 'english').toLowerCase().trim();
    if (langLower === "hindi") {
        return `💳 *ऑनलाइन भुगतान (Online Payment)* 💳\n\n` +
            `कुल राशि (Total): *₹${parseFloat(price).toFixed(2)}*\n\n` +
            `कृपया नीचे दिए गए किसी भी विकल्प का उपयोग करके भुगतान पूरा करें:\n` +
            `1. 📲 ऊपर दिए गए *QR कोड को स्कैन करें* किसी भी यूपीआई ऐप (Google Pay, PhonePe, Paytm आदि) से।\n` +
            `2. 🔗 या नीचे दिए गए *लिंक पर क्लिक करें*:\n` +
            `${plUrl}\n\n` +
            `⏳ _नोट: यह क्यूआर कोड और लिंक केवल 20 मिनट के लिए मान्य हैं।_`;
    } else if (langLower === "malayalam") {
        return `💳 *ഓൺലൈൻ പേയ്മെന്റ് (Online Payment)* 💳\n\n` +
            `ആകെ തുക (Total): *₹${parseFloat(price).toFixed(2)}*\n\n` +
            `ദയവായി താഴെ പറയുന്ന ഏതെങ്കിലും ഒരു മാർഗ്ഗം ഉപയോഗിച്ച് പണമടയ്ക്കുക:\n` +
            `1. 📲 മുകളിലുള്ള *QR കോഡ് സ്കാൻ ചെയ്യുക* (Google Pay, PhonePe, Paytm തുടങ്ങിയ ഏതെങ്കിലും UPI ആപ്പ് ഉപയോഗിച്ച്).\n` +
            `2. 🔗 അല്ലെങ്കിൽ താഴെ കാണുന്ന *ലിങ്ക് ക്ലിക്ക് ചെയ്യുക*:\n` +
            `${plUrl}\n\n` +
            `⏳ _ശ്രദ്ധിക്കുക: ഈ QR കോഡും ലിങ്കും 20 മിനിറ്റ് മാത്രമേ ലഭ്യമായിരിക്കുകയുള്ളൂ._`;
    } else if (langLower === "tamil") {
        return `💳 *ஆன்லைன் கட்டணம் (Online Payment)* 💳\n\n` +
            `மொத்த தொகை (Total): *₹${parseFloat(price).toFixed(2)}*\n\n` +
            `கீழೇ உள்ள ஏదేனும் ஒரு வழியைப் பயன்படுத்தி உங்கள் கட்டணத்தைச் செலுத்தவும்:\n` +
            `1. 📲 மேலே உள்ள *QR குறியீட்டை ஸ்கேன் செய்யவும்* (Google Pay, PhonePe, Paytm போன்ற ஏதேனும் ஒரு UPI செயலியைப் பயன்படுத்தி).\n` +
            `2. 🔗 அல்லது கீழே உள்ள *லிங்கைக் கிளிக் செய்யவும்*:\n` +
            `${plUrl}\n\n` +
            `⏳ _குறிப்பு: யூபிআই கியூஆர் குறியீடு மற்றும் கட்டண இணைப்பு இரண்டும் 20 நிமிடங்களில் காலாவதியாகிவிடும்._`;
    } else if (langLower === "telugu") {
        return `💳 *ఆన్‌లైన్ చెల్లింపు (Online Payment)* 💳\n\n` +
            `మొత్తం ధర (Total): *₹${parseFloat(price).toFixed(2)}*\n\n` +
            `దయచేసి క్రింది ఎంపికలలో దేనినైనా ఉపయోగించి మీ చెల్లింపును పూర్తి చేయండి:\n` +
            `1. 📲 పైన ఉన్న *QR కోడ్‌ను స్కాన్ చేయండి* (Google Pay, PhonePe, Paytm వంటి ఏదైనా UPI యాప్ ద్వారా).\n` +
            `2. 🔗 లేదా క్రింది *లింక్‌ను క్ಲಿక్ చేయండి*:\n` +
            `${plUrl}\n\n` +
            `⏳ _గమనిక: క్యూఆర్ కోడ్ మరియు పేమెంట్ లింక్ రెండూ 20 నిమిషాల్లో ముగుస్తాయి._`;
    } else if (langLower === "kannada") {
        return `💳 *ಆನ್‌ಲೈನ್ ಪಾವತಿ (Online Payment)* 💳\n\n` +
            `ಒಟ್ಟು ಮೊತ್ತ (Total): *₹${parseFloat(price).toFixed(2)}*\n\n` +
            `ದಯವಿಟ್ಟು ಕೆಳಗಿನ ಯಾವುದಾದರೊಂದು ಆಯ್ಕೆಯನ್ನು ಬಳಸಿ ಪಾವತಿಯನ್ನು ಪೂರ್ಣಗೊಳಿಸಿ:\n` +
            `1. 📲 ಮೇಲಿರುವ *QR ಕೋಡ್ ಅನ್ನು ಸ್ಕ್ಯಾನ್ ಮಾಡಿ* (Google Pay, PhonePe, Paytm ನಂತಹ ಯಾವುದೇ UPI ಆಪ್ ಬಳಸಿ).\n` +
            `2. 🔗 ಅಥವಾ ಕೆಳಗಿನ *ಲಿಂಕ್ ಅನ್ನು ಕ್ಲಿಕ್ ಮಾಡಿ*:\n` +
            `${plUrl}\n\n` +
            `⏳ _ಗಮನಿಸಿ: ಕ್ಯೂಆರ್ ಕೋಡ್ ಮತ್ತು ಪಾವತಿ ಲಿಂಕ್ ಎರಡೂ 20 ನಿಮಿಷಗಳಲ್ಲಿ ಮುಕ್ತಾಯಗೊಳ್ಳುತ್ತವೆ._`;
    } else {
        return `💳 *Online Payment Request* 💳\n\n` +
            `Total Amount: *₹${parseFloat(price).toFixed(2)}*\n\n` +
            `Please complete your payment using any of the options below:\n` +
            `1. 📲 *Scan the QR Code* above with any UPI app (Google Pay, PhonePe, Paytm, BHIM, etc.).\n` +
            `2. 🔗 Or *Click this Payment Link* to pay via UPI, Card, or NetBanking:\n` +
            `${plUrl}\n\n` +
            `⏳ _Note: Both the QR code and payment link will expire in 20 minutes._`;
    }
}


function findMatchingShopifyProducts(text, products) {
    if (!text || !products) return [];
    
    // Normalize and split into words of length >= 3
    const words = text.toLowerCase().split(/\W+/).filter(w => w.length >= 3);
    const stopWords = new Set(["for", "the", "and", "with", "from", "into", "your", "mens", "womens", "all", "get", "dry", "wet"]);
    const queryWords = words.filter(w => !stopWords.has(w));
    if (queryWords.length === 0) return [];
    
    const matched = [];
    for (const p of products) {
        const titleLower = p.title.toLowerCase();
        let matches = false;
        
        if (text.toLowerCase().trim().includes(titleLower)) {
            matches = true;
        } else {
            for (const qw of queryWords) {
                if (titleLower.includes(qw)) {
                    matches = true;
                    break;
                }
            }
        }
        
        if (matches && p.variants && p.variants[0]) {
            const bodyHtml = p.body_html || "";
            let cleanDesc = bodyHtml.replace(/<[^>]+>/g, '').trim();
            cleanDesc = cleanDesc.replace(/\s+/g, ' ');
            if (cleanDesc.length > 120) {
                cleanDesc = cleanDesc.slice(0, 117) + "...";
            }
            const imageUrl = p.images && p.images[0] ? p.images[0].src : null;

            matched.push({
                title: p.title,
                variant_id: p.variants[0].id,
                price: p.variants[0].price,
                handle: p.handle,
                description: cleanDesc,
                image_url: imageUrl
            });
        }
    }
    return matched;
}


  async function getShopifyProducts() {
    const storeDomain = process.env.SHOPIFY_STORE_DOMAIN || '2txc0h-0a.myshopify.com';
    const adminToken = await getShopifyAccessToken();
    if (!adminToken) {
        return [];
    }
    try {
        const url = `https://${storeDomain}/admin/api/2025-01/products.json?limit=250&fields=title,handle,variants,status,images,body_html`;
        const response = await fetch(url, {
            headers: {
                "X-Shopify-Access-Token": adminToken
            },
            signal: AbortSignal.timeout(8000)
        });
        if (response.ok) {
            const data = await response.json();
            return data.products || [];
        }
    } catch (e) {
        console.log(`[Shopify Products] Fetch failed: ${e.message}`);
    }
    return [];
}

async function handleAIFallback(sock, senderJid, text, senderName) {
    addLog(`[AIFallback] Processing AI response for ${senderName}...`);
    
    // 1. Build a COMPACT product context to avoid token overflow
    let context = "";

    // Load Shopify products from Admin API
    try {
        const shopifyProducts = await getShopifyProducts();
        if (shopifyProducts && shopifyProducts.length > 0) {
            context += "Store Products (from radikikk.shop):\n";
            shopifyProducts.forEach(p => {
                if (p.status === "active") {
                    const price = p.variants && p.variants[0] ? p.variants[0].price : "N/A";
                    const handle = p.handle || "";
                    const storeUrl = `https://radikikk.shop/products/${handle}`;
                    context += `- "${p.title}" | Price: ₹${price} | Link: ${storeUrl}\n`;
                }
            });
            context += "\n";
        }
    } catch (e) {
        addLog(`[AIFallback] Error loading Shopify products context: ${e.message}`);
    }

    // Load only keyword NAMES (not full reply texts) to keep context short
    try {
        const keywords = loadKeywords();
        const kwNames = Object.keys(keywords);
        if (kwNames.length > 0) {
            context += `Order trigger keywords (customer types one of these to place an order): ${kwNames.join(", ")}\n\n`;
        }
    } catch (e) {
        addLog(`[AIFallback] Error loading keywords: ${e.message}`);
    }

    // Load Instagram automations from local Flask API if running
    try {
        const response = await fetch(`http://127.0.0.1:${FB_BOT_PORT}/instagram/ui/automations`, { signal: AbortSignal.timeout(3000) });
        if (response.ok) {
            const autos = await response.json();
            if (autos && autos.length > 0) {
                context += "Instagram Promotions:\n";
                for (const auto of autos) {
                    if (auto.active) {
                        context += `- ${auto.name}`;
                        if (auto.link_url) context += ` | Link: ${auto.link_url}`;
                        context += "\n";
                    }
                }
                context += "\n";
            }
        }
    } catch (e) {
        // Quietly fail
    }

    // Load conversation state
    let convState = loadConvState();
    let userState = convState[senderJid];
    if (!userState) {
        userState = {
            step: "ai_chat",
            answers: {},
            paymentMethod: null,
            matchedKeywordPattern: null,
            updatedAt: Date.now()
        };
    }
    const currentAnswers = JSON.stringify(userState.answers, null, 2);

    const prompt = `
You are a helpful customer support agent for our online store.
Your goal is to answer the customer's question based strictly on the product catalog and promotions provided below. You also help them place orders by collecting their checkout details.

Customer Details:
Name: ${senderName}
Message: "${text}"
Current Checkout Answers collected so far:
${currentAnswers}

Our Product Catalog & Promotions:
${context}

Your response MUST be a valid JSON object containing exactly three keys:
1. "reply": A string containing your friendly response to the customer in their language. Do not include any greeting pleasantries or chitchat unless responding to a greeting. Ask politely for any missing ordering details.
2. "extracted_info": A JSON object containing any new or updated details extracted from the customer's current message:
   - "name": Customer full name (string or null)
   - "phone": Customer mobile phone number (string or null)
   - "address": Customer complete delivery shipping address (string or null)
   - "pincode": Delivery area pincode (string or null)
   - "product_title": The exact title of the product they want to order from the catalog list (string or null)
   - "payment_method": "cod" or "online" (string or null)
3. "ready_to_order": A boolean (true or false). Set this to true ONLY if you have successfully collected all of: name, phone, address, pincode, product_title, and payment_method.

Instructions:
1. Identify the customer's language and reply in the EXACT same language (e.g. Malayalam, Hinglish, English, etc.).
2. You must ONLY answer the customer's query directly. Do NOT include any small talk, greeting pleasantries (like "Hello!", "How can I help you today?"), or external chit-chat.
3. If they ask about a product, give them the matching catalog details (price, description) and link.
4. If they say they want to order, check what details are missing (e.g. name, address, payment method) and politely ask for those details in your "reply".
5. Do NOT answer anything unrelated to our products or ordering.
`;

    let aiMsg = null;

    // Try Groq Llama first
    const groqKey = process.env.GROQ_API_KEY;
    if (groqKey) {
        try {
            const resp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${groqKey}`
                },
                body: JSON.stringify({
                    model: "llama-3.3-70b-versatile",
                    messages: [{ role: "user", content: prompt }],
                    max_tokens: 1000,
                    temperature: 0.2
                }),
                signal: AbortSignal.timeout(10000)
            });
            if (resp.ok) {
                const data = await resp.json();
                aiMsg = data.choices[0].message.content.trim();
                addLog(`[AIFallback] Replied using Groq Llama 70B to ${senderName}.`);
            }
        } catch (err) {
            addLog(`[AIFallback] Groq Llama failed: ${err.message}`);
        }
    }

    // Try Gemini fallback
    if (!aiMsg) {
        const geminiKey = process.env.GEMINI_API_KEY || process.env.GEMINI_API_KEY_2;
        if (geminiKey) {
            try {
                const resp = await fetch("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "Authorization": `Bearer ${geminiKey}`
                    },
                    body: JSON.stringify({
                        model: "gemini-2.5-flash",
                        messages: [{ role: "user", content: prompt }],
                        max_tokens: 1000,
                        temperature: 0.2
                    }),
                    signal: AbortSignal.timeout(10000)
                });
                if (resp.ok) {
                    const data = await resp.json();
                    aiMsg = data.choices[0].message.content.trim();
                    addLog(`[AIFallback] Replied using Gemini Flash to ${senderName}.`);
                }
            } catch (err) {
                addLog(`[AIFallback] Gemini failed: ${err.message}`);
            }
        }
    }

    if (!aiMsg) {
        // Hard fallback if both AI APIs fail
        try {
            try { await sock.sendPresenceUpdate('paused', senderJid); } catch(e){}
            await sock.sendMessage(senderJid, { text: "Thanks for messaging us! Our support team will get back to you shortly. You can also type 'lolcat' to view our portable printer." });
            addLog(`[AIFallback] Sent default fallback reply to ${senderName}.`);
        } catch (e) {
            addLog(`[AIFallback] Failed to send fallback message: ${e.message}`);
        }
        return;
    }

    // Parse response
    let replyText = aiMsg;
    let extracted = {};
    let ready = false;

    try {
        let cleanRes = aiMsg.trim();
        if (cleanRes.startsWith("```")) {
            let lines = cleanRes.split("\n");
            if (lines.length > 2) {
                if (lines[0].toLowerCase().includes("json") || lines[0].trim() === "```") {
                    lines = lines.slice(1, -1);
                } else {
                    lines = lines.slice(1);
                }
            }
            cleanRes = lines.join("\n").trim();
        }
        const resData = JSON.parse(cleanRes);
        replyText = resData.reply || "";
        extracted = resData.extracted_info || {};
        ready = resData.ready_to_order || false;
    } catch (parseErr) {
        addLog(`[AIFallback] JSON parse error: ${parseErr.message}. Raw: ${aiMsg}`);
    }

    // Merge answers
    const updatedAnswers = userState.answers || {};
    for (const [k, v] of Object.entries(extracted)) {
        if (v) {
            updatedAnswers[k] = String(v);
            if (k === "payment_method") {
                userState.paymentMethod = String(v).toLowerCase();
            }
        }
    }
    userState.answers = updatedAnswers;
    userState.updatedAt = Date.now();

    if (ready) {
        // Find product title from live catalog
        const prodTitle = updatedAnswers.product_title;
        let resolved = null;
        try {
            const shopifyProducts = await getShopifyProducts();
            if (prodTitle && shopifyProducts) {
                const prodTitleLower = prodTitle.toLowerCase().trim();
                for (const p of shopifyProducts) {
                    if (prodTitleLower.includes(p.title.toLowerCase()) || p.title.toLowerCase().includes(prodTitleLower)) {
                        const price = p.variants && p.variants[0] ? p.variants[0].price : "N/A";
                        resolved = {
                            variant_id: p.variants[0].id,
                            price: price,
                            title: p.title
                        };
                        break;
                    }
                }
            }
        } catch (e) {
            addLog(`[AIFallback] Resolve products failed: ${e.message}`);
        }

        if (resolved) {
            userState.answers.variant_id = String(resolved.variant_id);
            userState.answers.price = String(resolved.price);
            userState.answers.product = resolved.title;
            userState.matchedKeywordPattern = "ai_chat";

            const payMethod = userState.paymentMethod || "cod";

            if (payMethod === "online") {
                try {
                    // Query Flask payment API
                    const paymentResp = await fetch(`http://127.0.0.1:${FB_BOT_PORT}/api/razorpay/create`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            sender_wa_id: senderJid,
                            sender_name: senderName,
                            price: resolved.price,
                            answers: userState.answers
                        })
                    });
                    if (paymentResp.ok) {
                        const payData = await paymentResp.json();
                        if (payData.ok) {
                            try { await sock.sendPresenceUpdate('paused', senderJid); } catch(e){}
                            
                            // Send AI reply
                            await sock.sendMessage(senderJid, { text: replyText });
                            
                            // Send QR
                            await sock.sendMessage(senderJid, {
                                image: { url: payData.qr_url },
                                caption: "ഇടപാട് പൂർത്തിയാക്കാൻ ഈ QR കോഡ് സ്കാൻ ചെയ്യുക (Scan this QR code to pay):"
                            });
                            
                            // Send Payment link
                            await sock.sendMessage(senderJid, { text: `അല്ലെങ്കിൽ താഴെ കാണുന്ന ലിങ്ക് ക്ലിക്ക് ചെയ്യുക (Or click here to pay): ${payData.payment_link_url}` });

                            // Clear state
                            delete convState[senderJid];
                            saveConvState(convState);
                            return;
                        }
                    }
                } catch (payErr) {
                    addLog(`[AIFallback] Online payment link query failed: ${payErr.message}`);
                }
                // Fallback to COD if payment generation fails
                await sock.sendMessage(senderJid, { text: "Sorry, we failed to generate the online payment link. Placing your order as Cash on Delivery instead." });
            }

            // Cash on Delivery
            try { await sock.sendPresenceUpdate('paused', senderJid); } catch(e){}
            await sock.sendMessage(senderJid, { text: replyText });
            try {
                await createShopifyOrderForState(userState, senderJid, senderName, sock);
            } catch (shopErr) {
                addLog(`[Shopify Error] AI COD order failed: ${shopErr.message}`);
            }

            delete convState[senderJid];
            saveConvState(convState);
        } else {
            try { await sock.sendPresenceUpdate('paused', senderJid); } catch(e){}
            await sock.sendMessage(senderJid, { text: "I couldn't match the product you mentioned to our catalog. Could you please specify which product from our catalog you want to order?" });
        }
    } else {
        convState[senderJid] = userState;
        saveConvState(convState);
        try { await sock.sendPresenceUpdate('paused', senderJid); } catch(e){}
        await sock.sendMessage(senderJid, { text: replyText });
    }
}


// Server setup
const app = express();
const server = http.createServer(app);
const io = new Server(server, {
    cors: { origin: "*" }
});

app.use(cors());

app.use('/yt', createProxyMiddleware({
    target: `http://127.0.0.1:${YT_BOT_PORT}`,
    changeOrigin: true,
    pathRewrite: { '^/yt': '' },
    on: {
        error: (err, req, res) => {
            console.error('[YT Proxy] Error:', err.message);
            if (!res.headersSent) {
                res.status(502).send('<html><body style="background:#07090f;color:#ef4444;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><div style="text-align:center"><div style="font-size:2rem">⚠️</div><div style="margin-top:1rem;font-size:1rem">YT Bot is starting up...<br><small style="color:#64748b">Refresh in a few seconds</small></div></div></body></html>');
            }
        }
    }
}));

app.use('/fb', createProxyMiddleware({
    target: `http://127.0.0.1:${FB_BOT_PORT}`,
    changeOrigin: true,
    on: {
        error: (err, req, res) => {
            console.error('[FB Proxy] Error:', err.message);
            if (!res.headersSent) {
                res.status(502).send('<html><body style="background:#07090f;color:#ef4444;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><div style="text-align:center"><div style="font-size:2rem">⚠️</div><div style="margin-top:1rem;font-size:1rem">FB Bot is starting up...<br><small style="color:#64748b">Refresh in a few seconds</small></div></div></body></html>');
            }
        }
    }
}));
app.use('/ig', createProxyMiddleware({
    target: `http://127.0.0.1:${FB_BOT_PORT}`,
    changeOrigin: true,
    on: {
        error: (err, req, res) => {
            console.error('[IG Proxy] Error:', err.message);
            if (!res.headersSent) {
                res.status(502).send('<html><body style="background:#07090f;color:#ef4444;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><div style="text-align:center"><div style="font-size:2rem">⚠️</div><div style="margin-top:1rem;font-size:1rem">IG Profile Service starting up...<br><small style="color:#64748b">Refresh in a few seconds</small></div></div></body></html>');
            }
        }
    }
}));
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ limit: '50mb', extended: true }));

// ── Proxy /yt/* → Python Flask YT bot ───────────────────────────────────────


app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/status', (req, res) => {
    res.json({
        status: connectionStatus,
        qr: qrCodeBase64,
        botNumber: sock && sock.user ? sock.user.id.split(':')[0].split('@')[0] : null
    });
});

app.get('/api/keywords', (req, res) => {
    res.json(loadKeywords());
});

app.post('/api/keywords', (req, res) => {
    const kwMap = req.body;
    if (saveKeywords(kwMap)) {
        res.json({ success: true, message: 'Keywords updated successfully.' });
        io.emit('keywords', kwMap);
    } else {
        res.status(500).json({ success: false, message: 'Failed to save keywords.' });
    }
});

app.get('/api/order-flow', (req, res) => {
    res.json(loadOrderFlowConfig());
});

app.post('/api/order-flow', (req, res) => {
    const config = req.body;
    if (!config || typeof config.payment_link !== 'string' || !Array.isArray(config.questions) || config.questions.length === 0) {
        return res.status(400).json({ success: false, message: 'Invalid config. payment_link must be a string and questions must be a non-empty array.' });
    }
    for (const q of config.questions) {
        if (!q || typeof q.key !== 'string' || typeof q.prompt !== 'string') {
            return res.status(400).json({ success: false, message: 'Each question must have a "key" and "prompt" (string).' });
        }
    }
    if (saveOrderFlowConfig(config)) {
        res.json({ success: true, message: 'Order flow configuration updated successfully.' });
        io.emit('order-flow', config);
    } else {
        res.status(500).json({ success: false, message: 'Failed to save order flow configuration.' });
    }
});

app.post('/api/keywords/save-rule', (req, res) => {
    const { key, rule } = req.body;
    if (!key) {
        return res.status(400).json({ success: false, message: 'Keyword trigger is required.' });
    }
    const kwMap = loadKeywords();
    kwMap[key] = rule;
    if (saveKeywords(kwMap)) {
        res.json({ success: true, message: 'Rule saved successfully.' });
        io.emit('keywords', kwMap);
    } else {
        res.status(500).json({ success: false, message: 'Failed to save rule.' });
    }
});

app.post('/api/keywords/delete-rule', (req, res) => {
    const { key } = req.body;
    if (!key) {
        return res.status(400).json({ success: false, message: 'Keyword trigger is required.' });
    }
    const kwMap = loadKeywords();
    delete kwMap[key];
    if (saveKeywords(kwMap)) {
        res.json({ success: true, message: 'Rule deleted successfully.' });
        io.emit('keywords', kwMap);
    } else {
        res.status(500).json({ success: false, message: 'Failed to delete rule.' });
    }
});

app.get('/api/logs', (req, res) => {
    res.json(logs);
});

app.get('/api/debug-ffmpeg', async (req, res) => {
    try {
        let exists = fs.existsSync(ffmpegPath);
        let stats = exists ? fs.statSync(ffmpegPath) : null;
        
        if (exists && process.platform !== 'win32') {
            try {
                fs.chmodSync(ffmpegPath, 0o755);
            } catch(e) {
                addLog(`chmod in debug route failed: ${e.message}`);
            }
        }

        const { stdout, stderr } = await execPromise(`"${ffmpegPath}" -version`);
        res.json({
            success: true,
            exists,
            stats,
            ffmpegPath,
            stdout,
            stderr
        });
    } catch (err) {
        res.json({
            success: false,
            exists: fs.existsSync(ffmpegPath),
            ffmpegPath,
            error: err.message,
            stack: err.stack
        });
    }
});


app.post('/api/logout', async (req, res) => {
    try {
        if (sock) {
            addLog('Logging out of WhatsApp and clearing session...');
            await sock.logout();
            sock = null;
        }
        // Clear auth folder
        const authStateDir = AUTH_DIR;
        if (fs.existsSync(authStateDir)) {
            fs.rmSync(authStateDir, { recursive: true, force: true });
        }
        if (fs.existsSync(SESSION_BACKUP_PATH)) {
            fs.unlinkSync(SESSION_BACKUP_PATH);
        }
        connectionStatus = 'Disconnected';
        isConnecting = false;
        qrCodeBase64 = null;
        io.emit('status', { status: connectionStatus });
        io.emit('qr', { qr: null });
        addLog('Session cleared. Reconnecting for fresh QR scan...');
        setTimeout(() => connectToWhatsApp(), 1500);
        res.json({ success: true, message: 'Logged out. Scan the new QR code.' });
    } catch (err) {
        addLog(`Logout error: ${err.message}`);
        // Force clear even if logout() fails
        const authStateDir = AUTH_DIR;
        try { if (fs.existsSync(authStateDir)) fs.rmSync(authStateDir, { recursive: true, force: true }); } catch(e) {}
        try { if (fs.existsSync(SESSION_BACKUP_PATH)) fs.unlinkSync(SESSION_BACKUP_PATH); } catch(e) {}
        sock = null;
        connectionStatus = 'Disconnected';
        isConnecting = false;
        qrCodeBase64 = null;
        io.emit('status', { status: connectionStatus });
        io.emit('qr', { qr: null });
        setTimeout(() => connectToWhatsApp(), 1500);
        res.json({ success: true, message: 'Session force-cleared. Scan the new QR code.' });
    }
});

app.post('/api/send', async (req, res) => {
    const { number, text, image, voice } = req.body;

    if (!number) {
        return res.status(400).json({ success: false, message: 'Recipient number is required.' });
    }

    const phoneId = process.env.WHATSAPP_PHONE_NUMBER_ID;
    const metaToken = process.env.PAGE_ACCESS_TOKEN;

    if (phoneId && metaToken) {
        try {
            addLog(`Manual message sending request to official Meta WhatsApp: ${number}`);
            await sendOfficialWAMessage(phoneId, metaToken, number, text, image, voice);
            addLog(`Message successfully sent via Meta WhatsApp Cloud API.`);
            return res.json({ success: true, message: 'Message sent successfully via Meta Cloud API.' });
        } catch (err) {
            addLog(`Failed to send message via Meta WhatsApp: ${err.message}`);
            return res.status(500).json({ success: false, message: `Failed to send message: ${err.message}` });
        }
    }

    if (connectionStatus !== 'Connected' || !sock) {
        return res.status(503).json({ success: false, message: 'WhatsApp bot is not connected.' });
    }

    // Format phone number to WhatsApp JID format (e.g. "919895138430@s.whatsapp.net")
    let jid = number.trim();
    if (!jid.endsWith('@s.whatsapp.net') && !jid.endsWith('@g.us') && !jid.endsWith('@newsletter')) {
        // Remove non-digit characters
        jid = jid.replace(/\D/g, '');
        jid = `${jid}@s.whatsapp.net`;
    }

    try {
        addLog(`Manual message sending request to: ${jid}`);

        // 1. Send image if provided
        if (image) {
            const imgBuffer = Buffer.from(image.split(',')[1] || image, 'base64');
            const mimeMatch = image.match(/^data:([^;]+);base64,/);
            const mimetype = mimeMatch ? mimeMatch[1] : 'image/jpeg';
            
            // Write image to a temp file and send via url path to avoid stream buffer issues in Baileys
            const tempImgPath = path.join(__dirname, `temp_image_${Math.random().toString(36).substring(7)}.jpg`);
            fs.writeFileSync(tempImgPath, imgBuffer);
            try {
                await sock.sendMessage(jid, { 
                    image: { url: tempImgPath }, 
                    mimetype: mimetype,
                    caption: voice ? undefined : text 
                });
                addLog(`Image successfully sent to: ${jid}`);
            } finally {
                if (fs.existsSync(tempImgPath)) {
                    try { fs.unlinkSync(tempImgPath); } catch (e) {}
                }
            }
        }

        // 2. Send voice note if provided
        if (voice) {
            addLog('Transcoding manual browser audio to OGG/Opus...');
            const { filePath, isTranscoded } = await convertToOggOpusFile(voice);
            try {
                await sock.sendMessage(jid, { 
                    audio: { url: filePath }, 
                    mimetype: isTranscoded ? 'audio/ogg; codecs=opus' : 'audio/webm', 
                    ptt: true 
                });
                addLog(`Voice note successfully sent to: ${jid}`);
            } finally {
                if (fs.existsSync(filePath)) {
                    try { fs.unlinkSync(filePath); } catch (e) {}
                }
            }
            
            // If there's text (and optionally an image, since caption was ignored when voice note was sent), send text separately:
            if (text) {
                await sock.sendMessage(jid, { text });
                addLog(`Separated text message successfully sent to: ${jid}`);
            }
        }


        // 3. Send text message if only text is provided (no image, no voice)
        if (text && !image && !voice) {
            // Baileys v7 auto-generates link previews via generateWAMessageContent
            await sock.sendMessage(jid, { text });
            addLog(`Text message successfully sent to: ${jid}`);
        }

        res.json({ success: true, message: 'Message sent successfully.' });
    } catch (err) {
        addLog(`Failed to manually send message to ${jid}: ${err.message}`);
        res.status(500).json({ success: false, message: `Failed to send message: ${err.message}` });
    }
});

function parseInviteCode(link) {
    if (!link) return null;
    const match = link.match(/chat\.whatsapp\.com\/([a-zA-Z0-9]{22,24})/);
    return match ? match[1] : link.trim();
}

app.post('/api/groups/add-all', async (req, res) => {
    const { groupLink } = req.body;
    if (!groupLink) {
        return res.status(400).json({ success: false, message: 'Group link is required.' });
    }
    if (connectionStatus !== 'Connected' || !sock) {
        return res.status(503).json({ success: false, message: 'WhatsApp bot is not connected.' });
    }
    const inviteCode = parseInviteCode(groupLink);
    if (!inviteCode) {
        return res.status(400).json({ success: false, message: 'Invalid WhatsApp group link.' });
    }
    
    // Respond immediately to the frontend so it doesn't wait/timeout
    res.json({ success: true, message: 'Group addition process started in background.' });

    try {
        addLog(`[Group Add] Resolving group invite code: ${inviteCode}`);
        let groupJid = null;
        try {
            const inviteInfo = await sock.groupGetInviteInfo(inviteCode);
            groupJid = inviteInfo.id;
            addLog(`[Group Add] Group JID resolved: ${groupJid} (${inviteInfo.subject})`);
        } catch (e) {
            addLog(`[Group Add] Failed to get invite info, trying to accept invite/join...`);
            groupJid = await sock.groupAcceptInvite(inviteCode);
            addLog(`[Group Add] Group JID resolved after joining: ${groupJid}`);
        }

        if (!groupJid) {
            addLog(`[Group Add] Error: Could not resolve group JID for code ${inviteCode}`);
            return;
        }

        const contacts = loadActiveContacts();
        addLog(`[Group Add] Found ${contacts.length} active contacts to process.`);

        for (const jid of contacts) {
            try {
                addLog(`[Group Add] Adding participant: ${jid.split('@')[0]}`);
                const response = await sock.groupParticipantsUpdate(groupJid, [jid], "add");
                
                let resStatus = null;
                if (response && response[0]) {
                    resStatus = response[0].status;
                } else if (response && response[jid]) {
                    resStatus = response[jid].status;
                }

                addLog(`[Group Add] Response status for ${jid.split('@')[0]}: ${resStatus}`);

                if (resStatus === '403') {
                    addLog(`[Group Add] Private invite needed for ${jid.split('@')[0]}. Sending invite message...`);
                    await sock.sendMessage(jid, { 
                        text: `Hi! Join our official WhatsApp group here: ${groupLink}` 
                    });
                }
            } catch (err) {
                addLog(`[Group Add] Failed to add or invite ${jid.split('@')[0]}: ${err.message}`);
            }
            // Delay 3 seconds between requests to avoid WhatsApp spam filter triggering
            await new Promise(resolve => setTimeout(resolve, 3000));
        }
        addLog(`[Group Add] Bulk addition process completed.`);
    } catch (err) {
        addLog(`[Group Add Error] Process failed: ${err.message}`);
    }
});

// ── /api/groups/add-all-chats: add every open chat thread (saved + unsaved) ─────
app.post('/api/groups/add-all-chats', async (req, res) => {
    const { groupLink } = req.body;
    if (!groupLink) {
        return res.status(400).json({ success: false, message: 'Group link is required.' });
    }
    if (connectionStatus !== 'Connected' || !sock) {
        return res.status(503).json({ success: false, message: 'WhatsApp bot is not connected.' });
    }
    const inviteCode = parseInviteCode(groupLink);
    if (!inviteCode) {
        return res.status(400).json({ success: false, message: 'Invalid WhatsApp group link.' });
    }

    // Flush chatMap into active_contacts.json before proceeding
    flushChatMap();

    // Respond immediately so the HTTP request doesn't time out
    res.json({ success: true, message: 'Add-all-chats process started in background.' });

    try {
        addLog(`[Group Add Chats] Resolving group invite code: ${inviteCode}`);
        let groupJid = null;
        try {
            const inviteInfo = await sock.groupGetInviteInfo(inviteCode);
            groupJid = inviteInfo.id;
            addLog(`[Group Add Chats] Group JID: ${groupJid} (${inviteInfo.subject})`);
        } catch (e) {
            groupJid = await sock.groupAcceptInvite(inviteCode);
            addLog(`[Group Add Chats] Group JID (after join): ${groupJid}`);
        }
        if (!groupJid) { addLog('[Group Add Chats] Could not resolve group JID.'); return; }

        const contacts = loadActiveContacts();
        // Only process individual chats (not groups — those end with @g.us)
        const individuals = contacts.filter(jid => jid.endsWith('@s.whatsapp.net'));
        addLog(`[Group Add Chats] ${individuals.length} individual chats to add (${contacts.length} total in DB, groups excluded).`);

        for (const jid of individuals) {
            try {
                addLog(`[Group Add Chats] Adding: ${jid.split('@')[0]}`);
                const response = await sock.groupParticipantsUpdate(groupJid, [jid], 'add');
                let resStatus = response?.[0]?.status ?? response?.[jid]?.status ?? null;
                addLog(`[Group Add Chats] Status for ${jid.split('@')[0]}: ${resStatus}`);
                if (resStatus === '403') {
                    await sock.sendMessage(jid, { text: `Hi! Join our group here: ${groupLink}` });
                    addLog(`[Group Add Chats] Sent invite link to ${jid.split('@')[0]}`);
                }
            } catch (err) {
                addLog(`[Group Add Chats] Direct add failed for ${jid.split('@')[0]}: ${err.message}. Sending invite message instead...`);
                try {
                    await sock.sendMessage(jid, { text: `Hi! Join our official WhatsApp group here: ${groupLink}` });
                    addLog(`[Group Add Chats] Sent invite link to ${jid.split('@')[0]}`);
                } catch (sendErr) {
                    addLog(`[Group Add Chats] Failed to send invite message to ${jid.split('@')[0]}: ${sendErr.message}`);
                }
            }
            await new Promise(r => setTimeout(r, 3000));
        }
        addLog('[Group Add Chats] Bulk addition completed.');
    } catch (err) {
        addLog(`[Group Add Chats Error] ${err.message}`);
    }
});

app.post('/api/groups/add-unsaved-chats', async (req, res) => {
    const { groupLink } = req.body;
    if (!groupLink) {
        return res.status(400).json({ success: false, message: 'Group link is required.' });
    }
    if (connectionStatus !== 'Connected' || !sock) {
        return res.status(503).json({ success: false, message: 'WhatsApp bot is not connected.' });
    }
    const inviteCode = parseInviteCode(groupLink);
    if (!inviteCode) {
        return res.status(400).json({ success: false, message: 'Invalid WhatsApp group link.' });
    }

    // Respond immediately to the frontend / client so it doesn't wait/timeout
    res.json({ success: true, message: 'Unsaved chats addition process started in background.' });

    try {
        addLog(`[Group Add Unsaved] Resolving group invite code: ${inviteCode}`);
        let groupJid = null;
        try {
            const inviteInfo = await sock.groupGetInviteInfo(inviteCode);
            groupJid = inviteInfo.id;
            addLog(`[Group Add Unsaved] Group JID resolved: ${groupJid} (${inviteInfo.subject})`);
        } catch (e) {
            addLog(`[Group Add Unsaved] Failed to get invite info, trying to accept invite/join...`);
            groupJid = await sock.groupAcceptInvite(inviteCode);
            addLog(`[Group Add Unsaved] Group JID resolved after joining: ${groupJid}`);
        }

        if (!groupJid) {
            addLog(`[Group Add Unsaved] Error: Could not resolve group JID for code ${inviteCode}`);
            return;
        }

        const active = loadActiveContacts();
        let saved = [];
        const savedContactsFile = path.join(__dirname, 'saved_contacts.json');
        if (fs.existsSync(savedContactsFile)) {
            try {
                saved = JSON.parse(fs.readFileSync(savedContactsFile, 'utf8'));
            } catch (e) {
                addLog(`[Group Add Unsaved] Failed to load saved_contacts.json: ${e.message}`);
            }
        }
        
        // Filter out contacts, only keep raw chats that are NOT saved contacts
        const unsaved = active.filter(jid => !saved.includes(jid));
        addLog(`[Group Add Unsaved] Found ${active.length} active chats, ${saved.length} saved contacts. Unsaved chats to process: ${unsaved.length}`);

        for (const jid of unsaved) {
            try {
                addLog(`[Group Add Unsaved] Adding participant: ${jid.split('@')[0]}`);
                const response = await sock.groupParticipantsUpdate(groupJid, [jid], "add");
                
                let resStatus = null;
                if (response && response[0]) {
                    resStatus = response[0].status;
                } else if (response && response[jid]) {
                    resStatus = response[jid].status;
                }

                addLog(`[Group Add Unsaved] Response status for ${jid.split('@')[0]}: ${resStatus}`);

                if (resStatus === '403') {
                    addLog(`[Group Add Unsaved] Private invite needed for ${jid.split('@')[0]}. Sending invite message...`);
                    await sock.sendMessage(jid, { 
                        text: `Hi! Join our official WhatsApp group here: ${groupLink}` 
                    });
                }
            } catch (err) {
                addLog(`[Group Add Unsaved] Failed to add or invite ${jid.split('@')[0]}: ${err.message}`);
            }
            // Delay 3 seconds between requests to avoid WhatsApp spam filter triggering
            await new Promise(resolve => setTimeout(resolve, 3000));
        }
        addLog(`[Group Add Unsaved] Bulk unsaved addition process completed.`);
    } catch (err) {
        addLog(`[Group Add Unsaved Error] Process failed: ${err.message}`);
    }
});

app.post('/api/export-session', (req, res) => {
    const authDir = AUTH_DIR;
    try {
        if (!fs.existsSync(authDir)) {
            return res.status(404).json({ success: false, message: 'No session to export.' });
        }
        const files = {};
        fs.readdirSync(authDir).forEach(f => {
            files[f] = fs.readFileSync(path.join(authDir, f), 'base64');
        });
        res.json({ success: true, session: Buffer.from(JSON.stringify(files)).toString('base64') });
    } catch(e) {
        res.status(500).json({ success: false, message: e.message });
    }
});

app.post('/api/import-session', async (req, res) => {
    const { session } = req.body;
    if (!session) return res.status(400).json({ success: false, message: 'No session data provided.' });
    const authDir = AUTH_DIR;
    try {
        const files = JSON.parse(Buffer.from(session, 'base64').toString('utf8'));
        if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
        Object.entries(files).forEach(([name, b64]) => {
            fs.writeFileSync(path.join(authDir, name), Buffer.from(b64, 'base64'));
        });
        // Also update the /tmp backup
        fs.writeFileSync(SESSION_BACKUP_PATH, JSON.stringify(files));
        addLog('Session imported. Reconnecting...');
        if (sock) { try { sock.end(); } catch(e) {} sock = null; }
        connectionStatus = 'Disconnected';
        isConnecting = false;
        setTimeout(() => connectToWhatsApp(), 1000);
        res.json({ success: true, message: 'Session imported. Reconnecting now.' });
    } catch(e) {
        res.status(500).json({ success: false, message: 'Invalid session data: ' + e.message });
    }
});

// ── Online Payment Webhook Shopify Order Fulfillment ──
app.post('/api/payment-webhook', async (req, res) => {
    const data = req.body;
    addLog(`Received payment success webhook: ${JSON.stringify(data)}`);
    
    // Extract identifier (phone, email, custom JID, etc.) from webhook data
    const identifier = data.phone || data.customer_phone || data.metadata?.jid || data.metadata?.phone || data.billing_details?.phone || data.email;
    
    if (!identifier) {
        return res.status(400).json({ success: false, message: 'Missing phone/JID identifier in webhook payload.' });
    }
    
    let targetJid = identifier.toString().trim();
    if (!targetJid.endsWith('@s.whatsapp.net')) {
        targetJid = targetJid.replace(/\D/g, '');
        targetJid = `${targetJid}@s.whatsapp.net`;
    }
    
    // Scan orders database to locate the user's latest pending online order
    const orders = loadOrders();
    const pendingOrderIdx = orders.slice().reverse().findIndex(o => 
        o.jid === targetJid && 
        o.paymentMethod === 'online' && 
        !o.shopifyProcessed
    );
    
    if (pendingOrderIdx === -1) {
        addLog(`[Shopify Error] No pending online order found for JID: ${targetJid}`);
        return res.status(404).json({ success: false, message: `No pending online order found for JID: ${targetJid}` });
    }
    
    const actualIdx = orders.length - 1 - pendingOrderIdx;
    const orderData = orders[actualIdx];
    
    try {
        const orderState = {
            answers: orderData.answers,
            paymentMethod: 'online'
        };
        
        if (sock) {
            await createShopifyOrderForState(orderState, orderData.jid, orderData.name, sock);
            
            // Mark as processed in orders database
            orderData.shopifyProcessed = true;
            orderData.shopifyProcessedAt = new Date().toISOString();
            orders[actualIdx] = orderData;
            saveOrders(orders);
            
            return res.json({ success: true, message: `Shopify order processed successfully for ${targetJid}` });
        } else {
            throw new Error('WhatsApp connection socket is not initialized/active.');
        }
    } catch(err) {
        addLog(`[Shopify Error] Webhook Shopify order creation failed: ${err.message}`);
        return res.status(500).json({ success: false, message: err.message });
    }
});

// Socket connection listener
io.on('connection', (socket) => {
    socket.emit('status', { status: connectionStatus });
    socket.emit('qr', { qr: qrCodeBase64 });
    socket.emit('keywords', loadKeywords());
    socket.emit('logs-init', logs);
});

let sock = null;
let qrCodeBase64 = null;
let connectionStatus = 'Disconnected'; // Disconnected, Connecting, Connected, Scanning
let isConnecting = false;

// Plain in-memory chat map — populated from Baileys events on every connection
const chatMap = new Map(); // jid -> true
function registerChat(id) {
    if (id && typeof id === 'string' && !chatMap.has(id)) {
        chatMap.set(id, true);
        addContact(id); // also persist to active_contacts.json
    }
}
function flushChatMap() {
    chatMap.forEach((_, id) => addContact(id));
    addLog(`[Chat Sync] Flushed ${chatMap.size} chats from in-memory map.`);
}

async function connectToWhatsApp() {
    const phoneId = process.env.WHATSAPP_PHONE_NUMBER_ID;
    const metaToken = process.env.PAGE_ACCESS_TOKEN;
    if (phoneId && metaToken) {
        connectionStatus = 'Connected';
        qrCodeBase64 = null;
        io.emit('status', { status: connectionStatus });
        addLog('Official WhatsApp Cloud API mode is enabled. Node socket is running in Webhook listener mode.');
        isConnecting = false;
        return;
    }

    if (isConnecting) return;
    isConnecting = true;

    // Use AUTH_DIR env var for Railway persistent volume, fallback to local
    const authStateDir = AUTH_DIR;
    
    // Attempt to restore session from /tmp backup if auth dir is empty or missing
    if (!fs.existsSync(authStateDir) || fs.readdirSync(authStateDir).length === 0) {
        restoreSession(authStateDir);
    }
    
    const { state, saveCreds } = await useMultiFileAuthState(authStateDir);
    
    // Fetch latest WhatsApp Web version to prevent protocol mismatch errors
    let version = [2, 3000, 1034074495]; // Safe fallback — updated for 2025 protocol
    try {
        const { version: latestVer, isLatest } = await fetchLatestBaileysVersion();
        version = latestVer;
        addLog(`Fetched latest WhatsApp Web version: ${version.join('.')}, isLatest: ${isLatest}`);
    } catch (err) {
        addLog(`Could not fetch latest WA version, using fallback: ${err.message}`);
    }

    addLog('Initializing WhatsApp socket connection (with active persistent volume)...');
    connectionStatus = 'Connecting';
    io.emit('status', { status: connectionStatus });

    try {
        sock = makeWASocket({
            version,
            auth: state,
            printQRInTerminal: false,
            logger: pino({ level: 'silent' }),
            // Browser fingerprint — required by Baileys v7 to avoid 401 handshake failures
            browser: ['WhatsApp Bot', 'Chrome', '125.0.0'],
            // Prevent premature timeout during QR auth (important for v7)
            defaultQueryTimeoutMs: undefined,
            // Keep connection alive
            keepAliveIntervalMs: 25000,
            // Generate high quality link preview
            generateHighQualityLinkPreview: true,
        });

        sock.ev.on('creds.update', async () => {
            await saveCreds();
            // Also back up to /tmp so session survives Railway container restarts
            backupSession(authStateDir);
        });

        sock.ev.on('messaging-history.set', ({ chats, contacts, messages }) => {
            if (chats) {
                chats.forEach(c => { registerChat(c.id); addContact(c.id); });
                addLog(`[History Sync] Loaded ${chats.length} chats from history.`);
            }
            if (contacts) {
                try {
                    let savedJids = [];
                    const savedContactsFile = path.join(__dirname, 'saved_contacts.json');
                    if (fs.existsSync(savedContactsFile)) {
                        savedJids = JSON.parse(fs.readFileSync(savedContactsFile, 'utf8'));
                    }
                    let updated = false;
                    contacts.forEach(c => {
                        if (c.id && c.id.endsWith('@s.whatsapp.net') && !savedJids.includes(c.id)) {
                            savedJids.push(c.id);
                            updated = true;
                        }
                    });
                    if (updated) {
                        fs.writeFileSync(savedContactsFile, JSON.stringify(savedJids, null, 2), 'utf8');
                    }
                    addLog(`[History Sync] Loaded ${contacts.length} contacts from history.`);
                } catch(e) {
                    console.error('Error handling contacts in history set:', e);
                }
            }
        });

        // Sync chats list to maintain our active inbox contacts database
        sock.ev.on('chats.set', ({ chats }) => {
            if (chats) {
                chats.forEach(c => { registerChat(c.id); addContact(c.id); });
                addLog(`[Chat Sync] chats.set: ${chats.length} chats loaded.`);
            }
        });

        sock.ev.on('chats.upsert', (chats) => {
            if (chats) {
                chats.forEach(c => { registerChat(c.id); addContact(c.id); });
            }
        });

        sock.ev.on('contacts.set', ({ contacts }) => {
            if (contacts) {
                try {
                    const savedJids = contacts.map(c => c.id).filter(id => id && id.endsWith('@s.whatsapp.net'));
                    const savedContactsFile = path.join(__dirname, 'saved_contacts.json');
                    fs.writeFileSync(savedContactsFile, JSON.stringify(savedJids, null, 2), 'utf8');
                    addLog(`[Contact Sync] Synced ${savedJids.length} saved contacts.`);
                } catch(e) {
                    console.error('Error saving contacts:', e);
                }
            }
        });

        sock.ev.on('contacts.upsert', (contacts) => {
            if (contacts) {
                try {
                    let savedJids = [];
                    const savedContactsFile = path.join(__dirname, 'saved_contacts.json');
                    if (fs.existsSync(savedContactsFile)) {
                        savedJids = JSON.parse(fs.readFileSync(savedContactsFile, 'utf8'));
                    }
                    let updated = false;
                    contacts.forEach(c => {
                        if (c.id && c.id.endsWith('@s.whatsapp.net') && !savedJids.includes(c.id)) {
                            savedJids.push(c.id);
                            updated = true;
                        }
                    });
                    if (updated) {
                        fs.writeFileSync(savedContactsFile, JSON.stringify(savedJids, null, 2), 'utf8');
                    }
                } catch(e) {
                    console.error('Error updating contacts:', e);
                }
            }
        });

        sock.ev.on('connection.update', async (update) => {
            const { connection, lastDisconnect, qr } = update;
            
            if (qr) {
                connectionStatus = 'Scanning';
                io.emit('status', { status: connectionStatus });
                try {
                    qrCodeBase64 = await QRCode.toDataURL(qr);
                    io.emit('qr', { qr: qrCodeBase64 });
                    addLog('New QR Code generated. Scan it via the web dashboard.');
                } catch (err) {
                    addLog('Error converting QR code to base64 image.');
                }
            }

            if (connection === 'close') {
                isConnecting = false;
                const statusCode = lastDisconnect?.error?.output?.statusCode || lastDisconnect?.error?.code;
                const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
                
                connectionStatus = 'Disconnected';
                qrCodeBase64 = null;
                io.emit('status', { status: connectionStatus });
                io.emit('qr', { qr: null });
                
                addLog(`Connection closed. Error: ${lastDisconnect?.error?.message || 'Unknown reason'} (Status code: ${statusCode}). Reconnecting: ${shouldReconnect}`);
                
                if (shouldReconnect) {
                    addLog('Reconnecting in 5 seconds...');
                    setTimeout(() => connectToWhatsApp(), 5000);
                } else {
                    addLog('Logged out from WhatsApp. Clearing session credentials...');
                    try {
                        fs.rmSync(authStateDir, { recursive: true, force: true });
                        addLog('Session directory cleared successfully.');
                    } catch (e) {
                        addLog(`Failed to clear session directory: ${e.message}`);
                    }
                    try {
                        if (fs.existsSync(SESSION_BACKUP_PATH)) {
                            fs.unlinkSync(SESSION_BACKUP_PATH);
                            addLog('Session backup file cleared successfully.');
                        }
                    } catch (e) {
                        addLog(`Failed to clear session backup file: ${e.message}`);
                    }
                    addLog('Restarting connection for fresh QR code in 3 seconds...');
                    setTimeout(() => connectToWhatsApp(), 3000);
                }
            } else if (connection === 'open') {
                isConnecting = false;
                connectionStatus = 'Connected';
                qrCodeBase64 = null;
                // Backup fresh session immediately after successful QR scan
                backupSession(authStateDir);
                addLog('WhatsApp Connection established successfully!');

                io.emit('status', { status: connectionStatus });
                io.emit('qr', { qr: null });

                // Flush in-memory chat map into active_contacts.json on every connect
                setTimeout(() => {
                    try {
                        flushChatMap();
                    } catch(e) {
                        addLog(`[Chat Sync] Store flush failed: ${e.message}`);
                    }
                }, 5000); // 5s delay to let WhatsApp finish sending initial sync payloads
            } else if (connection === 'connecting') {
                connectionStatus = 'Connecting';
                io.emit('status', { status: connectionStatus });
                addLog('Connecting to WhatsApp API...');
            }
        });

        sock.ev.on('messages.upsert', async (m) => {
            if (m.type !== 'notify') return;
            
            for (const msg of m.messages) {
                // Track contacts from every message exchange
                if (msg.key && msg.key.remoteJid) {
                    addContact(msg.key.remoteJid);
                }
                const partJid = msg.key?.participant || msg.participant;
                if (partJid) {
                    addContact(partJid);
                }

                if (msg.key.fromMe) continue;
                
                const messageType = Object.keys(msg.message || {})[0];
                let text = '';
                if (messageType === 'conversation') {
                    text = msg.message.conversation;
                } else if (messageType === 'extendedTextMessage') {
                    text = msg.message.extendedTextMessage.text;
                } else if (msg.message?.buttonsResponseMessage) {
                    text = msg.message.buttonsResponseMessage.selectedButtonId || '';
                } else if (msg.message?.templateButtonReplyMessage) {
                    text = msg.message.templateButtonReplyMessage.selectedId || '';
                } else if (msg.message?.listResponseMessage) {
                    text = msg.message.listResponseMessage.singleSelectReply?.selectedRowId || '';
                } else if (msg.message?.orderMessage) {
                    const orderMsg = msg.message.orderMessage;
                    addLog(`[Baileys OrderMessage] received: ${JSON.stringify(orderMsg)}`);
                    if (orderMsg.token) {
                        text = `order_variant_${orderMsg.token}`;
                    }
                }
                
                if (!text) continue;
                
                const senderJid = msg.key.remoteJid;
                const senderName = msg.pushName || 'WhatsApp User';
                addLog(`Received message from ${senderName} (${senderJid}): "${text}"`);
                // Store the original message for quoted reply
                const quotedMsg = msg;
                
                // --- Conversation State Interception ---
                const orderFlowConfig = loadOrderFlowConfig();
                const convState = loadConvState();

                if (text.startsWith("order_variant_")) {
                    const variantId = text.replace("order_variant_", "");
                    const shopifyProducts = await getShopifyProducts();
                    let matchedP = null;
                    for (const p of shopifyProducts) {
                        if (p.variants && p.variants[0] && String(p.variants[0].id) === variantId) {
                            matchedP = p;
                            break;
                        }
                    }
                    if (matchedP) {
                        const price = matchedP.variants[0].price;
                        convState[senderJid] = {
                            step: 'awaiting_payment_choice',
                            matchedKeywordPattern: "custom_variant_" + variantId,
                            paymentMethod: null,
                            answers: {
                                product_title: matchedP.title,
                                variant_id: String(variantId),
                                variant: String(variantId),
                                price: String(price),
                                product: matchedP.title
                            },
                            updatedAt: Date.now()
                        };
                        saveConvState(convState);
                        
                        await sock.sendMessage(senderJid, { text: `🛍️ *${matchedP.title}*\nPrice: ₹${price}\n\nLet's start your order!` });
                        
                        const choiceText =
                            `How would you like to pay?\n\n` +
                            `*1* - ${orderFlowConfig.cod_label}\n` +
                            `*2* - ${orderFlowConfig.online_label}\n` +
                            `*3* - Cancel\n\n` +
                            `Just reply with 1, 2 or 3.`;

                        const buttons = [
                            { buttonId: 'order_cod', buttonText: { displayText: orderFlowConfig.cod_label }, type: 1 },
                            { buttonId: 'order_online', buttonText: { displayText: orderFlowConfig.online_label }, type: 1 },
                            { buttonId: 'order_cancel', buttonText: { displayText: 'Cancel' }, type: 1 }
                        ];

                        await sock.sendMessage(senderJid, {
                            text: choiceText,
                            buttons: buttons,
                            headerType: 1
                        });
                        continue;
                    }
                } else if (text.startsWith("ask_variant_")) {
                    const variantId = text.replace("ask_variant_", "");
                    const shopifyProducts = await getShopifyProducts();
                    let matchedP = null;
                    for (const p of shopifyProducts) {
                        if (p.variants && p.variants[0] && String(p.variants[0].id) === variantId) {
                            matchedP = p;
                            break;
                        }
                    }
                    if (matchedP) {
                        await handleAIFallback(sock, senderJid, `Explain what the product '${matchedP.title}' is and answer any questions about it.`, senderName);
                        continue;
                    }
                }

                const userState = convState[senderJid];

                if (userState && orderFlowConfig.enabled) {
                    try { await sock.readMessages([msg.key]); } catch (e) {}

                    let incomingText = text.trim();
                    const buttonReply = msg.message?.buttonsResponseMessage?.selectedButtonId;
                    if (buttonReply) incomingText = buttonReply;

                    const lowerInput = incomingText.toLowerCase();
                    if (lowerInput === 'cancel' || lowerInput === 'restart' || lowerInput === 'order_cancel') {
                        delete convState[senderJid];
                        saveConvState(convState);
                        await sock.sendMessage(senderJid, { text: "No problem, flow cancelled. Message us again anytime!" });
                        continue;
                    }

                    if (userState.step === 'awaiting_second_message') {
                        userState.step = 'awaiting_payment_choice';
                        userState.updatedAt = Date.now();
                        convState[senderJid] = userState;
                        saveConvState(convState);

                        const choiceText =
                            `How would you like to pay?\n\n` +
                            `*1* - ${orderFlowConfig.cod_label}\n` +
                            `*2* - ${orderFlowConfig.online_label}\n` +
                            `*3* - Cancel\n\n` +
                            `Just reply with 1, 2 or 3.`;

                        const buttons = [
                            { buttonId: 'order_cod', buttonText: { displayText: orderFlowConfig.cod_label }, type: 1 },
                            { buttonId: 'order_online', buttonText: { displayText: orderFlowConfig.online_label }, type: 1 },
                            { buttonId: 'order_cancel', buttonText: { displayText: 'Cancel' }, type: 1 }
                        ];

                        const buttonMessage = {
                            text: choiceText,
                            buttons: buttons,
                            headerType: 1
                        };

                        try {
                            await sock.sendMessage(senderJid, buttonMessage);
                            addLog(`Sent interactive payment choice to ${senderName}.`);
                        } catch (err) {
                            addLog(`Button message failed, falling back to text reply.`);
                            await sock.sendMessage(senderJid, { text: choiceText });
                        }
                        continue;
                    }

                    if (userState.step === 'awaiting_payment_choice') {
                        const lower = incomingText.toLowerCase();
                        const isCod = lower === '1' || lower === 'cod' || lower === 'order_cod' || lower.includes('cash');
                        const isOnline = lower === '2' || lower === 'online' || lower === 'order_online' || lower.includes('online');
                        const isCancel = lower === '3' || lower === 'cancel' || lower === 'order_cancel';

                        if (isCancel) {
                            delete convState[senderJid];
                            saveConvState(convState);
                            await sock.sendMessage(senderJid, { text: "No problem, flow cancelled. Message us again anytime!" });
                            continue;
                        }

                        if (isCod || isOnline) {
                            userState.paymentMethod = isCod ? 'cod' : 'online';
                            userState.step = 'asking_question_0';
                            userState.updatedAt = Date.now();
                            convState[senderJid] = userState;
                            saveConvState(convState);

                            const firstQuestion = orderFlowConfig.questions[0];
                            const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                            await delay(1000);
                            await sock.sendMessage(senderJid, { text: firstQuestion.prompt });
                        } else {
                            await sock.sendMessage(senderJid, {
                                text: `Sorry, I didn't get that. Please reply with *1* for ${orderFlowConfig.cod_label}, *2* for ${orderFlowConfig.online_label}, or *3* to cancel.`
                            });
                        }
                        continue;
                    }

                    if (userState.step === 'confirm_address') {
                        const lower = incomingText.toLowerCase().trim();
                        const isConfirm = lower === 'confirm' || lower === 'yes' || lower === 'correct' || lower === '1' || lower === 'addr_confirm';
                        const isReenter = lower === 'reenter' || lower === 'no' || lower === 'change' || lower === 're-enter' || lower === '2' || lower === 'addr_reenter';
                        const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

                        if (isConfirm) {
                            userState.step = 'asking_question_3'; // proceed to pincode
                            userState.updatedAt = Date.now();
                            convState[senderJid] = userState;
                            saveConvState(convState);

                            await delay(800);
                            await sock.sendMessage(senderJid, { text: orderFlowConfig.questions[3].prompt });
                        } else if (isReenter) {
                            const prevAddress = userState.answers.address || '';
                            userState.step = 'asking_question_2'; // back to address
                            userState.updatedAt = Date.now();
                            convState[senderJid] = userState;
                            saveConvState(convState);

                            await delay(800);
                            await sock.sendMessage(senderJid, {
                                text: `Your previously entered address was:\n\n"${prevAddress}"\n\nPlease reply with your correct shipping address. 🏠`
                            });
                        } else {
                            const prevAddress = userState.answers.address || '';
                            const confirmText = `🏠 *Please confirm your Shipping Address:* \n\n${prevAddress}\n\nIs this correct?`;
                            const buttons = [
                                { buttonId: 'addr_confirm', buttonText: { displayText: 'Confirm' }, type: 1 },
                                { buttonId: 'addr_reenter', buttonText: { displayText: 'Re-enter' }, type: 1 }
                            ];
                            await delay(800);
                            try {
                                await sock.sendMessage(senderJid, {
                                    text: confirmText,
                                    buttons: buttons,
                                    headerType: 1
                                });
                            } catch (err) {
                                await sock.sendMessage(senderJid, { text: `${confirmText}\n\nReply *Confirm* or *Re-enter*.` });
                            }
                        }
                        continue;
                    }

                    if (userState.step.startsWith('asking_question_')) {
                        const currentIdx = parseInt(userState.step.replace('asking_question_', ''), 10);
                        const currentQuestion = orderFlowConfig.questions[currentIdx];

                        userState.answers[currentQuestion.key] = incomingText;
                        
                        if (currentIdx === 2) {
                            userState.step = 'confirm_address';
                            userState.updatedAt = Date.now();
                            convState[senderJid] = userState;
                            saveConvState(convState);

                            const confirmText = `🏠 *Please confirm your Shipping Address:* \n\n${incomingText}\n\nIs this correct?`;
                            const buttons = [
                                { buttonId: 'addr_confirm', buttonText: { displayText: 'Confirm' }, type: 1 },
                                { buttonId: 'addr_reenter', buttonText: { displayText: 'Re-enter' }, type: 1 }
                            ];
                            const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                            await delay(800);
                            try {
                                await sock.sendMessage(senderJid, {
                                    text: confirmText,
                                    buttons: buttons,
                                    headerType: 1
                                });
                            } catch (err) {
                                await sock.sendMessage(senderJid, { text: `${confirmText}\n\nReply *Confirm* or *Re-enter*.` });
                            }
                            continue;
                        }

                        const nextIdx = currentIdx + 1;
                        const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

                        if (nextIdx < orderFlowConfig.questions.length) {
                            userState.step = `asking_question_${nextIdx}`;
                            userState.updatedAt = Date.now();
                            convState[senderJid] = userState;
                            saveConvState(convState);

                            await delay(800);
                            await sock.sendMessage(senderJid, { text: orderFlowConfig.questions[nextIdx].prompt });
                        } else {
                            // All questions answered — send the final confirmation.
                            if (userState.paymentMethod === 'online') {
                                try {
                                    const price = userState.answers.price || '999';
                                    const paymentResp = await fetch(`http://127.0.0.1:${FB_BOT_PORT}/api/razorpay/create`, {
                                        method: "POST",
                                        headers: { "Content-Type": "application/json" },
                                        body: JSON.stringify({
                                            sender_wa_id: senderJid,
                                            sender_name: senderName,
                                            price: price,
                                            answers: userState.answers
                                        })
                                    });
                                    if (paymentResp.ok) {
                                        const payData = await paymentResp.json();
                                        if (payData.ok) {
                                            const captionText = getPaymentInstructionText('english', price, payData.payment_link_url);
                                            await sock.sendMessage(senderJid, {
                                                image: { url: payData.qr_url },
                                                caption: captionText
                                            });
                                        }
                                    }
                                } catch (payErr) {
                                    addLog(`[Checkout] Online payment link query failed: ${payErr.message}`);
                                    await sock.sendMessage(senderJid, { text: "Sorry, we had trouble generating your online payment. Placing your order as Cash on Delivery instead." });
                                    userState.paymentMethod = 'cod';
                                }
                            }

                            if (userState.paymentMethod === 'cod') {
                                const template = orderFlowConfig.cod_confirmation_template;
                                let finalText = template;
                                for (const [key, value] of Object.entries(userState.answers)) {
                                    finalText = finalText.split(`{${key}}`).join(value);
                                }
                                await delay(1000);
                                await sock.sendMessage(senderJid, { text: finalText });
                            }
                            
                            addLog(`Order flow completed for ${senderName} (${userState.paymentMethod}).`);

                            // Send order notification to owner 916282444918
                            try {
                                const ownerJid = '916282444918@s.whatsapp.net';
                                const answersText = Object.entries(userState.answers)
                                    .map(([k, v]) => `*${k}*: ${v}`)
                                    .join('\n');
                                const ownerNotification = 
                                    `📦 *New Order Received!*\n\n` +
                                    `*Customer*: ${senderName} (${senderJid.split('@')[0]})\n` +
                                    `*Payment Mode*: ${userState.paymentMethod === 'cod' ? 'Cash on Delivery' : 'Online Payment'}\n\n` +
                                    `*Details*:\n${answersText}`;
                                await sock.sendMessage(ownerJid, { text: ownerNotification });
                                addLog(`Owner notification sent to 916282444918.`);
                            } catch (err) {
                                addLog(`Failed to send notification to owner: ${err.message}`);
                            }

                            const orders = loadOrders();
                            const orderRecord = {
                                jid: senderJid,
                                name: senderName,
                                paymentMethod: userState.paymentMethod,
                                answers: userState.answers,
                                matchedKeywordPattern: userState.matchedKeywordPattern,
                                completedAt: new Date().toISOString()
                            };
                            orders.push(orderRecord);
                            saveOrders(orders);

                            // Trigger Shopify order creation automatically for COD orders
                            if (userState.paymentMethod === 'cod') {
                                createShopifyOrderForState(userState, senderJid, senderName, sock)
                                    .then(() => {
                                        const updatedOrders = loadOrders();
                                        const lastIdx = updatedOrders.length - 1;
                                        if (lastIdx >= 0 && updatedOrders[lastIdx].jid === senderJid) {
                                            updatedOrders[lastIdx].shopifyProcessed = true;
                                            updatedOrders[lastIdx].shopifyProcessedAt = new Date().toISOString();
                                            saveOrders(updatedOrders);
                                        }
                                    })
                                    .catch(err => addLog(`[Shopify Error] COD auto-creation failed: ${err.message}`));
                            }

                            delete convState[senderJid];
                            saveConvState(convState);
                        }
                        continue;
                    }
                }

                // Match keywords
                const kwMap = loadKeywords();
                const cleanText = text.trim().toLowerCase();
                let matched = false;
                
                for (const [kwPattern, ruleData] of Object.entries(kwMap)) {
                    // Support comma-separated keywords (e.g. "host, hoster, hostinger")
                    const keywords = kwPattern.split(',').map(k => k.trim().toLowerCase()).filter(k => k.length > 0);
                    const isMatch = keywords.some(kw => matchKeyword(cleanText, kw));
                    
                    if (isMatch) {
                        addLog(`Keyword match found in pattern "${kwPattern}". Replying automatically...`);
                        try {
                            // Normalize simple string rules to object rules for backward compatibility
                            const rule = typeof ruleData === 'string'
                                ? { text: ruleData, image: null, voice: null }
                                : ruleData;
                                
                            const { text: replyText, image: replyImage, voice: replyVoice } = rule;
                            if (rule.sendCatalog) {
                                addLog(`⚠️ [Baileys Mode] Pattern "${kwPattern}" triggered a Catalog rule, but Meta Catalog Messages are only supported in Official Cloud API mode. Falling back to text response.`);
                            }

                            const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

                            // Mark message as read BEFORE replying - critical for delivery
                            try {
                                await sock.readMessages([msg.key]);
                            } catch (e) {}

                            // Subscribe to sender's presence so WhatsApp doesn't treat us as offline bot
                            try {
                                await sock.presenceSubscribe(senderJid);
                            } catch (e) {}
                            const setPresence = async (type) => {
                                try {
                                    await sock.sendPresenceUpdate(type, senderJid);
                                } catch (e) {}
                            };

                            // Initial reaction delay (simulate human reading/noticing)
                            await delay(1000);

                            // 1. Send image if provided
                            if (replyImage) {
                                await setPresence('composing');
                                await delay(2000); // Simulate upload/processing time
                                
                                const imgBuffer = Buffer.from(replyImage.split(',')[1] || replyImage, 'base64');
                                const mimeMatch = replyImage.match(/^data:([^;]+);base64,/);
                                const mimetype = mimeMatch ? mimeMatch[1] : 'image/jpeg';
                                addLog(`Image buffer size: ${imgBuffer.length} bytes, mimetype: ${mimetype}`);
                                
                                const tempImgPath = path.join(__dirname, `temp_image_${Math.random().toString(36).substring(7)}.jpg`);
                                fs.writeFileSync(tempImgPath, imgBuffer);
                                try {
                                    await sock.sendMessage(senderJid, { 
                                        image: { url: tempImgPath }, 
                                        mimetype: mimetype,
                                        caption: replyVoice ? undefined : replyText 
                                    });
                                    addLog(`Auto-reply sent image to ${senderName}.`);
                                } finally {
                                    if (fs.existsSync(tempImgPath)) {
                                        try { fs.unlinkSync(tempImgPath); } catch (e) {}
                                    }
                                }
                                
                                await setPresence('paused');
                                await delay(1500); // Small interval between messages
                            }

                            // 2. Send voice note if provided
                            if (replyVoice) {
                                await setPresence('recording');
                                addLog('Transcoding auto-reply audio to OGG/Opus...');
                                const { filePath, isTranscoded } = await convertToOggOpusFile(replyVoice);
                                
                                try {
                                    await delay(3500); // Simulate audio recording duration
                                    await sock.sendMessage(senderJid, { 
                                        audio: { url: filePath }, 
                                        mimetype: isTranscoded ? 'audio/ogg; codecs=opus' : 'audio/webm', 
                                        ptt: true 
                                    });
                                    addLog(`Auto-reply sent voice note to ${senderName}.`);
                                } finally {
                                    if (fs.existsSync(filePath)) {
                                        try { fs.unlinkSync(filePath); } catch (e) {}
                                    }
                                }
                                
                                await setPresence('paused');
                                await delay(1500); // Small interval before next message
                                
                                if (replyText) {
                                    await setPresence('composing');
                                    const typingDuration = Math.min(1500 + replyText.length * 15, 6000);
                                    await delay(typingDuration);
                                    
                                    await sock.sendMessage(senderJid, { text: replyText });
                                    addLog(`Auto-reply sent text message separately to ${senderName}.`);
                                    
                                    await setPresence('paused');
                                }
                            }

                            // 3. Send text message if only text is provided (no image, no voice)
                            if (replyText && !replyImage && !replyVoice) {
                                await setPresence('composing');
                                const typingDuration = Math.min(1500 + replyText.length * 15, 6000);
                                await delay(typingDuration);

                                // Baileys v7 auto-generates link previews via generateWAMessageContent
                                // when sendMessage is called with { text } — no manual linkPreview needed
                                await sock.sendMessage(senderJid, { text: replyText });
                                addLog(`Auto-reply sent text to ${senderName}.`);
                                
                            }

                            const orderFlowConfig = loadOrderFlowConfig();
                            if (rule.useOrderFlow && orderFlowConfig.enabled) {
                                const convState = loadConvState();
                                convState[senderJid] = {
                                    step: 'awaiting_second_message',
                                    matchedKeywordPattern: kwPattern,
                                    paymentMethod: null,
                                    answers: {},
                                    updatedAt: Date.now()
                                };
                                saveConvState(convState);
                                addLog(`Initialized order flow in awaiting_second_message state for ${senderName}.`);
                            }

                             matched = true;
                             break; // Stop after first match
                        } catch (err) {
                            addLog(`Failed to send message: ${err.message}`);
                        }
                    }
                }
                
                if (!matched) {
                    const shopifyProducts = await getShopifyProducts();
                    const matchedProducts = findMatchingShopifyProducts(text, shopifyProducts);
                    
                    if (matchedProducts.length > 0) {
                        const catalogId = process.env.META_CATALOG_ID;
                        if (catalogId) {
                            try {
                                if (matchedProducts.length === 1) {
                                    const p = matchedProducts[0];
                                    await sock.sendMessage(senderJid, {
                                        product: {
                                            product: {
                                                productId: String(p.variant_id)
                                            },
                                            businessOwnerJid: sock.user.id.split(':')[0] + '@s.whatsapp.net'
                                        },
                                        caption: `Check out *${p.title}*! Price: ₹${p.price}`
                                    });
                                    addLog(`[Shopify Intercept] Sent native single product for ${p.title} to ${senderName}`);
                                } else {
                                    // Send list message with products
                                    const sections = [{
                                        title: 'Shopify Products',
                                        rows: matchedProducts.slice(0, 30).map(p => ({
                                            title: p.title,
                                            rowId: `order_variant_${p.variant_id}`,
                                            description: `Price: ₹${p.price}`
                                        }))
                                    }];
                                    await sock.sendMessage(senderJid, {
                                        text: 'We found these products in our catalog. Click below to view!',
                                        buttonText: 'View Products',
                                        sections: sections
                                    });
                                    addLog(`[Shopify Intercept] Sent native multi-product list to ${senderName}`);
                                }
                                continue;
                            } catch (catErr) {
                                addLog(`[Shopify Intercept] Native catalog send failed, falling back to cards: ${catErr.message}`);
                            }
                        }

                        // Fallback (or default if catalogId is not set) -> Send beautiful custom card messages
                        for (const p of matchedProducts.slice(0, 3)) {
                            const bodyText = `🛍️ *${p.title}*\n\nPrice: ₹${p.price}\n\n_${p.description}_\n\nLink: https://radikikk.shop/products/${p.handle}`;
                            const buttons = [
                                { buttonId: `order_variant_${p.variant_id}`, buttonText: { displayText: "Order Now" }, type: 1 },
                                { buttonId: `ask_variant_${p.variant_id}`, buttonText: { displayText: "Ask Details" }, type: 1 }
                            ];
                            
                            try {
                                if (p.image_url) {
                                    await sock.sendMessage(senderJid, {
                                        image: { url: p.image_url },
                                        caption: bodyText,
                                        buttons: buttons,
                                        headerType: 4 // Image header
                                    });
                                } else {
                                    await sock.sendMessage(senderJid, {
                                        text: bodyText,
                                        buttons: buttons,
                                        headerType: 1
                                    });
                                }
                                addLog(`[Shopify Intercept] Sent card for ${p.title} to ${senderName}`);
                                await new Promise(r => setTimeout(r, 800)); // Small interval
                            } catch (e) {
                                addLog(`[Shopify Intercept Card Error] ${e.message}`);
                            }
                        }
                        continue;
                    }

                    await handleAIFallback(sock, senderJid, text, senderName);
                }
            }
        });

        // Track message delivery acknowledgements (1=sent, 2=delivered, 3=read, -1=error)
        sock.ev.on('messages.update', (updates) => {
            for (const update of updates) {
                if (update.key.fromMe) {
                    const ack = update.update?.status;
                    if (ack === 1) addLog(`📤 Message sent (1 tick) to ${update.key.remoteJid?.split('@')[0]}`);
                    else if (ack === 2) addLog(`✅ Message delivered (2 ticks) to ${update.key.remoteJid?.split('@')[0]}`);
                    else if (ack === 3) addLog(`👁️ Message read by ${update.key.remoteJid?.split('@')[0]}`);
                    else if (ack === -1) addLog(`❌ Message failed/rejected by WhatsApp for ${update.key.remoteJid?.split('@')[0]}`);
                }
            }
        });
    } catch (err) {
        isConnecting = false;
        addLog(`Error initializing socket: ${err.message}`);
        setTimeout(() => connectToWhatsApp(), 5000);
    }
}

server.listen(EXPRESS_PORT, () => {
    addLog(`Server is running on port ${EXPRESS_PORT}`);
    addLog(`Dashboard URL: http://localhost:${EXPRESS_PORT}`);
    addLog(`Persistent storage path: ${persistentDir || 'None (using local fallback)'}`);
    connectToWhatsApp();
    startYTBot();
    startFBBot();
    startReposterDaemon();
});

