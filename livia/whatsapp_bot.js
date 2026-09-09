const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const { exec } = require('child_process');
const ocr = require("node-tesseract-ocr");
const fs = require('fs'); // For Announcement File Watching
const path = require('path'); // For Announcement File Pathing

// Tesseract engine configuration matrix
const ocrConfig = {
    lang: "eng",
    oem: 3,
    psm: 3,
};

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: path.join(__dirname, 'sessions') }),
    puppeteer: {
        headless: true,
        executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome-stable',
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

let clientReady = false;

client.on('qr', (qr) => {
    console.log('--- SCAN THIS QR CODE WITH YOUR WHATSAPP TO CONNECT THE BOT ---');
    qrcode.generate(qr, { small: true });
});

client.on('ready', () => {
    clientReady = true;
    console.log('Livia AI WhatsApp gateway is online!');
});

// =============================================================================
// 📡 INTERNAL SEND API — lets other local services (CoreRipper's Django backend,
// for monitor alerts) send an outbound WhatsApp message through this same
// authenticated session. Localhost-only, not exposed publicly.
//
//   POST http://127.0.0.1:3001/send
//   { "number": "15551234567", "message": "..." }
//   number = digits only (country code + number, no '+', spaces, or dashes) —
//   this handler strips anything else before building the WhatsApp chat id.
//
// Matches the probe contract in backend/monitors/whatsapp.py: connection error
// = bot process down, 503 = bot up but session not linked, 400 on an empty
// body = ready (reaches payload validation).
// =============================================================================
const express = require('express');
const sendApi = express();
sendApi.use(express.json());

sendApi.post('/send', async (req, res) => {
    if (!clientReady) {
        return res.status(503).json({ status: 'error', message: 'WhatsApp client is not ready yet.' });
    }
    const { number, message } = req.body || {};
    const digits = String(number || '').replace(/[^0-9]/g, '');
    if (!digits || !message) {
        return res.status(400).json({ status: 'error', message: "'number' and 'message' are required." });
    }
    try {
        await client.sendMessage(`${digits}@c.us`, message);
        res.json({ status: 'sent' });
    } catch (error) {
        console.error('❌ /send failed:', error.message);
        res.status(500).json({ status: 'error', message: error.message });
    }
});

sendApi.listen(3001, '127.0.0.1', () => {
    console.log('📡 Internal send API listening on http://127.0.0.1:3001 (localhost only)');
});

// =============================================================================
// 📢 MASS ANNOUNCEMENT SYSTEM (FILE WATCHER)
// =============================================================================
const announcementFilePath = path.join(__dirname, 'announcement.txt');

// Ensure the announcement file exists cleanly
if (!fs.existsSync(announcementFilePath)) {
    fs.writeFileSync(announcementFilePath, '', 'utf8');
}

// Watch the announcement file for modifications every 1 second
fs.watchFile(announcementFilePath, { interval: 1000 }, async (curr, prev) => {
    if (curr.mtime <= prev.mtime) return; // File didn't change content safely

    try {
        const text = fs.readFileSync(announcementFilePath, 'utf8').trim();
        if (!text) return; // File is empty, do nothing

        console.log(`📢 Target Announcement Detected: "${text}"`);

        // ⚠️ REPLACE THIS with your true group ID when you grab it from your terminal logs!
        const targetGroupId = '120363422734230937@g.us'; 

        const chat = await client.getChatById(targetGroupId);
        
        if (chat.isGroup) {
            // Create a clean message body using the universal tag layout
            let announcementText = `📢 *@all* \n\n${text}`;

            // Fetch all current participant IDs to attach in the background metadata
            let participantIds = chat.participants.map(p => p.id._serialized);

            // Fire the payload - it pings everyone at once without listing names out loud
            await client.sendMessage(targetGroupId, announcementText, { 
                mentions: participantIds 
            });
            
            console.log('✅ Clean mass announcement blasted successfully.');

            // Wipe the file clean so it doesn't loop fire
            fs.writeFileSync(announcementFilePath, '', 'utf8');
        }
    } catch (error) {
        console.error('❌ Announcement pipeline failure:', error);
    }
});

// =========================================================================
// MAIN INBOUND CHAT DISPATCHER (TEXT & IMAGES)
// =========================================================================
client.on('message_create', async (msg) => {
    // 🔍 THIS WILL PRINT THE GROUP ID TO YOUR PM2 LOGS FOR ANY INBOUND MESSAGE:
    //console.log(`➡️ Message incoming from ID: ${msg.from}`);

    if (msg.fromMe) return;

    let shouldRespond = false;
    let textToAnalyze = "";

    // SCENARIO A: User uploaded a screenshot image
    if (msg.hasMedia && (msg.type === 'image' || msg.type === 'sticker')) {
        try {
            console.log(`\n📸 Image received. Activating Livia AI Vision Core...`);
            
            // Download the raw encrypted media file from WhatsApp servers
            const media = await msg.downloadMedia();
            if (!media || !media.data) return;

            // Convert base64 data stream into an optimized buffer array
            const imageBuffer = Buffer.from(media.data, 'base64');

            // Scan the pixel matrices to extract readable text strings
            const extractedText = await ocr.recognize(imageBuffer, ocrConfig);
            console.log(`📝 OCR Extracted Text: \n"${extractedText.trim()}"`);

            // Look for keywords in the image to determine if it's an error screenshot
            const lowerText = extractedText.toLowerCase();
            if (lowerText.includes("socksip") || lowerText.includes("custom") || lowerText.includes("error") || lowerText.includes("stuck") || lowerText.includes("fail") || lowerText.includes("timeout")) {
                shouldRespond = true;
                textToAnalyze = extractedText;
                console.log("🎯 Relevant VPN context found inside screenshot!");
            }
        } catch (ocrError) {
            console.error(`❌ Vision Processing Failure: ${ocrError.message}`);
        }
    } 
    // SCENARIO B: Classic Text Conversations
    else {
        const cleanBody = msg.body ? msg.body.trim() : "";
        if (!cleanBody) return;

        if (cleanBody.toLowerCase().startsWith('Livia AI')) {
            shouldRespond = true;
            textToAnalyze = cleanBody.slice(5).trim();
            
            if (!textToAnalyze) {
                msg.reply("Yes? I am here to help");
                return;
            }
        } else if (msg.hasQuotedMsg) {
            const quotedMsg = await msg.getQuotedMessage();
            if (quotedMsg.fromMe) {
                shouldRespond = true;
                textToAnalyze = cleanBody;
            }
        }
    }

    // RUN THE BRAIN SYSTEM MODEL ENGINE
    if (shouldRespond && textToAnalyze) {
        // Sanitize string to prevent terminal execution injections
        const sanitizedQuery = textToAnalyze.replace(/[^a-zA-Z0-9 ]/g, " ");

        console.log(`🧠 Handing data to AI model: "${sanitizedQuery.substring(0, 50)}..."`);

        const pythonPath = '/home/clive/anaconda3/bin/python';
        const scriptPath = path.join(__dirname, 'train_brain.py');
        
        // Match your exact original execution formatting style
        exec(`${pythonPath} ${scriptPath} "${sanitizedQuery}"`, (error, stdout, stderr) => {
            if (error) {
                console.error(`❌ AI Engine Fault: ${error.message}`);
                return;
            }

            const aiReply = stdout.trim();
            
            // Rejection Gate: Handle unknown errors or low confidence predictions explicitly
            if (aiReply.startsWith("I'm not completely sure")) {
                const fallbackMessage = "Hmm, I'm not quite sure about that one! 🤔 Please wait for an admin to come online";
                console.log(`⚠️ Unknown error encountered. Livia AI sending fallback notification.`);
                msg.reply(fallbackMessage);
                return;
            }

            console.log(`🤖 Livia AI Replied: "${aiReply}"`);
            msg.reply(aiReply);
        });
    }
});

// NEW MEMBER INTERCEPTOR
client.on('group_join', async (notification) => {
    try {
        const chat = await notification.getChat();
        const newMembers = notification.recipientIds;
        for (let memberId of newMembers) {
            const cleanNumber = memberId.split('@')[0];
            const welcomeGreeting = `Welcome to the Community, @${cleanNumber}! 🎉\n\nI am *Livia AI*. Send me screenshots of any configuration errors or text *\"Livia AI help\"* and I will be here to help`;
            await chat.sendMessage(welcomeGreeting, { mentions: [memberId] });
        }
    } catch (error) { console.error(error); }
});

client.initialize();
