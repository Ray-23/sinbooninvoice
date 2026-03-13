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
const latestPricesPath = path.join(dataDir, 'prices', 'latest_prices.json');
fs.mkdirSync(authDir, { recursive: true });
fs.mkdirSync(logDir, { recursive: true });
fs.mkdirSync(incomingDir, { recursive: true });

const orderGroupName = process.env.ORDER_GROUP_NAME || process.env.TARGET_GROUP_NAME || '';
const priceGroupName = process.env.PRICE_GROUP_NAME || '';
const watchedGroups = [orderGroupName, priceGroupName].filter(Boolean);
if (!orderGroupName || !priceGroupName) {
  console.error('Missing ORDER_GROUP_NAME and/or PRICE_GROUP_NAME.');
  console.error('Example: ORDER_GROUP_NAME="SinboonInvoice" PRICE_GROUP_NAME="SinboonPrice" npm start');
  process.exit(1);
}

const logger = P({ level: 'info' }, P.destination(path.join(logDir, 'listener.log')));
let missingGroupNames = new Set();

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

function parseChildOutput(stdout) {
  try {
    return JSON.parse(stdout);
  } catch {
    return null;
  }
}

function ingestMessage({ messageType, chatId, groupName, sender, messageId, text }) {
  return new Promise((resolve, reject) => {
    const child = spawn('python3', [
      path.join(rootDir, 'scripts', 'ingest_message.py'),
      '--stdin',
      '--source',
      'whatsapp',
      '--message-type',
      messageType,
      '--chat-id',
      chatId,
      '--group-name',
      groupName,
      '--sender',
      sender || '',
      '--message-id',
      messageId || '',
    ], {
      cwd: rootDir,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (buf) => { stdout += buf.toString(); });
    child.stderr.on('data', (buf) => { stderr += buf.toString(); });
    child.on('close', (code) => {
      if (code === 0) {
        const parsedOutput = parseChildOutput(stdout);
        logger.info({ event: 'ingested', messageType, chatId, groupName, messageId, stdout: parsedOutput || stdout });
        resolve({ stdout, parsedOutput });
      } else {
        logger.error({ event: 'ingest_failed', messageType, chatId, groupName, messageId, stderr, code });
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
  console.log(`Order group: ${orderGroupName}`);
  console.log(`Price group: ${priceGroupName}`);
  console.log(`Incoming files: ${incomingDir}`);
  console.log(`Latest prices catalog: ${latestPricesPath}`);
  console.log(`Session/auth files: ${authDir}`);
  console.log(`Listener log: ${path.join(logDir, 'listener.log')}`);
  console.log('');
}

async function verifyTargetGroups(sock) {
  const groups = await refreshGroups(sock);
  const availableGroupNames = new Set(Object.values(groups).map((group) => group?.subject).filter(Boolean));
  const missingNames = watchedGroups.filter((groupName) => !availableGroupNames.has(groupName));

  if (missingNames.length > 0) {
    for (const groupName of missingNames) {
      if (!missingGroupNames.has(groupName)) {
        console.error(`Target group not found: "${groupName}"`);
      }
    }
    if (missingNames.some((groupName) => !missingGroupNames.has(groupName))) {
      console.error('Open WhatsApp on your phone, confirm both group names match exactly, then wait for sync or restart the listener.');
    }
    missingGroupNames = new Set(missingNames);
    logger.error({ event: 'target_groups_missing', missingNames, watchedGroups });
  } else {
    if (missingGroupNames.size > 0) {
      console.log('All configured WhatsApp groups are now available.');
    }
    missingGroupNames = new Set();
    logger.info({ event: 'target_groups_found', watchedGroups });
  }

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
      console.log(`Watching order group: ${orderGroupName}`);
      console.log(`Watching price group: ${priceGroupName}`);
      logger.info({ event: 'connected', orderGroupName, priceGroupName });
      void verifyTargetGroups(sock);
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
    const groups = await verifyTargetGroups(sock);

    for (const msg of messages) {
      try {
        if (!msg.key?.remoteJid?.endsWith('@g.us')) continue;
        const chatId = msg.key.remoteJid;
        const groupName = groups?.[chatId]?.subject || '';
        if (!watchedGroups.includes(groupName)) continue;

        const text = extractText(msg.message);
        if (!text) continue;

        const messageType = groupName === priceGroupName ? 'price' : 'order';
        const sender = msg.pushName || msg.key.participant || 'Unknown';
        console.log(`Captured WhatsApp ${messageType} message from "${groupName}"`);
        console.log(`Sender: ${sender}`);
        console.log(`Message ID: ${msg.key.id || 'unknown'}`);
        logger.info({ event: 'message_received', messageType, chatId, groupName, sender, messageId: msg.key.id });

        const { parsedOutput } = await ingestMessage({
          messageType,
          chatId,
          groupName,
          sender,
          messageId: msg.key.id,
          text,
        });

        if (messageType === 'price') {
          console.log(`Saved price raw message under: ${parsedOutput?.saved_raw_to || path.join(dataDir, 'prices', 'raw')}`);
          console.log(`Saved price history snapshot under: ${parsedOutput?.saved_history_to || path.join(dataDir, 'prices', 'history')}`);
          console.log(`Latest price catalog: ${parsedOutput?.latest_catalog_path || latestPricesPath}`);
          if (parsedOutput?.latest_catalog_updated === false) {
            console.log('Latest price catalog was not replaced because a newer price snapshot already exists.');
          }
        } else {
          console.log(`Saved pending review file under: ${parsedOutput?.saved_to || incomingDir}`);
        }
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
