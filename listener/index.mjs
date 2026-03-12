import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';
import P from 'pino';
import qrcode from 'qrcode-terminal';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { spawn } from 'child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');
const authDir = path.join(__dirname, 'auth_info_baileys');
const dataDir = path.join(rootDir, 'data');
const logDir = path.join(dataDir, 'logs');
const incomingDir = path.join(dataDir, 'incoming');
fs.mkdirSync(authDir, { recursive: true });
fs.mkdirSync(logDir, { recursive: true });
fs.mkdirSync(incomingDir, { recursive: true });

const targetGroupName = process.env.TARGET_GROUP_NAME || '';
if (!targetGroupName) {
  console.error('Missing TARGET_GROUP_NAME. Example: TARGET_GROUP_NAME="Veg Orders" npm start');
  process.exit(1);
}

const logger = P({ level: 'info' }, P.destination(path.join(logDir, 'listener.log')));
let targetGroupFound = false;

function extractText(message) {
  if (!message) return '';
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    message.documentMessage?.caption ||
    ''
  ).trim();
}

function ingestMessage({ chatId, groupName, sender, messageId, text }) {
  return new Promise((resolve, reject) => {
    const child = spawn('python3', [path.join(rootDir, 'scripts', 'ingest_message.py'), '--stdin', '--source', 'whatsapp', '--chat-id', chatId, '--group-name', groupName, '--sender', sender || '', '--message-id', messageId || ''], {
      cwd: rootDir,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (buf) => { stdout += buf.toString(); });
    child.stderr.on('data', (buf) => { stderr += buf.toString(); });
    child.on('close', (code) => {
      if (code === 0) {
        logger.info({ event: 'ingested', chatId, groupName, messageId, stdout });
        resolve(stdout);
      } else {
        logger.error({ event: 'ingest_failed', chatId, groupName, messageId, stderr, code });
        reject(new Error(stderr || `Ingest failed with code ${code}`));
      }
    });

    child.stdin.write(text);
    child.stdin.end();
  });
}

async function refreshGroups(sock) {
  try {
    return await sock.groupFetchAllParticipating();
  } catch (error) {
    logger.error({ event: 'group_fetch_failed', error: String(error) });
    return {};
  }
}

function printStartupBanner() {
  console.log('Order Bot WhatsApp Listener');
  console.log(`Target group: ${targetGroupName}`);
  console.log(`Incoming files: ${incomingDir}`);
  console.log(`Session/auth files: ${authDir}`);
  console.log(`Listener log: ${path.join(logDir, 'listener.log')}`);
  console.log('');
}

async function verifyTargetGroup(sock) {
  const groups = await refreshGroups(sock);
  const matchedEntry = Object.entries(groups).find(([, group]) => group?.subject === targetGroupName);

  if (!matchedEntry) {
    if (!targetGroupFound) {
      console.error(`Target group not found: "${targetGroupName}"`);
      console.error('Open WhatsApp on your phone, confirm the group name matches exactly, then wait for sync or restart the listener.');
    }
    targetGroupFound = false;
    logger.error({ event: 'target_group_not_found', targetGroupName });
    return groups;
  }

  targetGroupFound = true;
  logger.info({ event: 'target_group_found', targetGroupName, chatId: matchedEntry[0] });
  return groups;
}

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  const { version, isLatest } = await fetchLatestBaileysVersion();
  printStartupBanner();
  console.log(`Baileys protocol version: ${version.join('.')} (${isLatest ? 'latest known' : 'fallback'})`);

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false,
    browser: ['OrderBot Prototype', 'Chrome', '1.0.0'],
    syncFullHistory: false,
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      console.log('\nScan this QR with WhatsApp on your phone:\n');
      qrcode.generate(qr, { small: true });
      logger.info({ event: 'qr_generated' });
    }

    if (connection === 'open') {
      console.log('WhatsApp connection established.');
      console.log(`Watching for messages from: ${targetGroupName}`);
      logger.info({ event: 'connected', targetGroupName });
      void verifyTargetGroup(sock);
    }

    if (connection === 'close') {
      const statusCode = new Boom(lastDisconnect?.error)?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      logger.error({ event: 'connection_closed', statusCode, shouldReconnect });
      if (shouldReconnect) connect();
      else console.log('Logged out. Delete listener/auth_info_baileys and reconnect.');
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    const groups = await verifyTargetGroup(sock);

    for (const msg of messages) {
      try {
        if (!msg.key?.remoteJid?.endsWith('@g.us')) continue;
        const chatId = msg.key.remoteJid;
        const groupName = groups?.[chatId]?.subject || '';
        if (groupName !== targetGroupName) continue;

        const text = extractText(msg.message);
        if (!text) continue;

        const sender = msg.pushName || msg.key.participant || 'Unknown';
        console.log(`Captured WhatsApp message from "${groupName}"`);
        console.log(`Sender: ${sender}`);
        console.log(`Message ID: ${msg.key.id || 'unknown'}`);
        logger.info({ event: 'message_received', chatId, groupName, sender, messageId: msg.key.id });
        await ingestMessage({ chatId, groupName, sender, messageId: msg.key.id, text });
        console.log(`Saved pending review file under: ${incomingDir}`);
      } catch (error) {
        logger.error({ event: 'message_process_error', error: String(error) });
        console.error('Failed to process message:', error.message || error);
      }
    }
  });
}

connect().catch((error) => {
  console.error('Listener failed to start:', error);
  process.exit(1);
});
