/**
 * Gmail Webhook Parser
 *
 * Lightweight utilities for parsing Gmail Pub/Sub webhook notifications.
 * The MCP server handles all Gmail API interactions - this just parses notifications.
 */

export interface GmailNotification {
  emailAddress: string;
  historyId: string;
}

export interface PubSubMessage {
  message: {
    data: string;
    messageId: string;
    publishTime: string;
  };
  subscription: string;
}

/**
 * Parse a Pub/Sub push notification from Gmail
 */
export function parsePubSubNotification(body: PubSubMessage): GmailNotification {
  const { message } = body;

  if (!message || !message.data) {
    throw new Error('Invalid Pub/Sub message: missing data field');
  }

  // Decode base64 data
  const decodedData = Buffer.from(message.data, 'base64').toString('utf-8');
  const data = JSON.parse(decodedData);

  if (!data.emailAddress || !data.historyId) {
    throw new Error('Invalid Gmail notification: missing emailAddress or historyId');
  }

  return {
    emailAddress: data.emailAddress,
    historyId: data.historyId.toString(),
  };
}

/**
 * Extract email address from "Name <email>" format
 */
export function extractEmailAddress(emailString: string): string {
  const match = emailString.match(/<(.+?)>/);
  return match ? match[1] : emailString.trim();
}

/**
 * Strip quoted reply text from email body
 * Removes common quote patterns like "> ", "On ... wrote:", etc.
 */
export function stripQuotedReply(body: string): string {
  const lines = body.split('\n');
  const cleanedLines: string[] = [];

  let inQuote = false;

  for (const line of lines) {
    // Detect start of quoted section
    if (
      line.trim().startsWith('>') ||
      line.match(/^On .+ wrote:/) ||
      line.match(/^From:.*Sent:.*To:/)
    ) {
      inQuote = true;
      continue;
    }

    if (!inQuote) {
      cleanedLines.push(line);
    }
  }

  return cleanedLines.join('\n').trim();
}

/**
 * Verify Pub/Sub token (basic validation)
 * For production, you should validate the JWT token from Google
 */
export function verifyPubSubToken(message: PubSubMessage['message']): boolean {
  // Basic validation - message has required fields
  if (!message || !message.messageId || !message.publishTime) {
    return false;
  }

  // In production, you would:
  // 1. Verify the JWT token in the Authorization header
  // 2. Check that the subscription matches your expected subscription
  // 3. Validate the message signature

  return true;
}
