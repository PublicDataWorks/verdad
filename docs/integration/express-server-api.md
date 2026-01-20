# Express Server & API

## Express Server & API

The VERDAD Express server acts as the central coordination hub for the platform's collaborative features. It manages real-time communication via Liveblocks, synchronizes collaborative data with the Supabase database, and handles outgoing notifications to Slack and email.

### Core API Endpoints

The server exposes a set of REST endpoints primarily used for authentication and processing external webhooks.

#### Authentication
*   **`POST /api/liveblocks-auth`**
    *   **Purpose:** Authenticates frontend users for Liveblocks sessions, allowing them to participate in real-time document editing and commenting.
    *   **Input:** Liveblocks auth request.
    *   **Output:** Authorization token for the frontend client.

#### Webhooks
*   **`POST /api/webhooks/liveblocks`**
    *   **Purpose:** Listens for events from the Liveblocks service (e.g., when a comment is created, a reaction is added, or a thread is deleted).
    *   **Processing:** Triggers downstream database updates in Supabase and sends relevant notifications to analysts.

---

### Comment & Collaboration Services

The server ensures that all real-time interactions occurring in the frontend are persisted and searchable in the primary database.

#### Synchronization Logic
The `commentService` manages the flow of data between Liveblocks and Supabase. Key operations include:

*   **Comment Persistence:** When a user leaves a comment on a radio snippet, the server catches the webhook and mirrors the content in the `comments` table.
*   **Reaction Tracking:** Captures and stores emoji reactions (upvotes/labels) to improve AI heuristics over time.
*   **Batch Syncing:** An internal script (`server/src/index.ts`) is available to perform a full reconciliation between Liveblocks rooms and the database to ensure data integrity.

```typescript
// Example: Data structure for comment synchronization
{
  id: string;          // Unique comment ID
  thread_id: string;   // Reference to the discussion thread
  room_id: string;     // Reference to the specific audio snippet
  created_by: string;  // User ID of the analyst
  body: string;        // JSON string of the comment content
  comment_at: string;  // Timestamp
}
```

---

### Notification System

VERDAD keeps researchers and journalists informed of new findings or discussion activity through a tiered notification system.

#### Email Notifications
Powered by **Resend**, the `emailService` handles transactional emails. It uses templates stored in Supabase to provide context-aware alerts (e.g., @mentions in a snippet discussion).

#### Slack Integration
The `slackService` enables team-wide visibility into platform activity. It formats events—such as new disinformation snippets or critical comments—into structured alerts.

*   **Notification Types:** Mentions, new comments, edited content, and deletions.
*   **Delivery:** Notifications are routed to a configured Slack notification email address, which then posts them to the designated team channel.

---

### Configuration & Environment Variables

To run the Express server, the following environment variables must be configured:

| Variable | Description |
| :--- | :--- |
| `SUPABASE_URL` | The URL of your Supabase project. |
| `SUPABASE_SERVICE_ROLE_KEY` | Administrative key for database operations. |
| `LIVEBLOCKS_SECRET_KEY` | Secret key for managing real-time rooms. |
| `RESEND_API_KEY` | API key for sending notification emails. |
| `SLACK_NOTIFICATION_EMAIL` | The destination email for Slack channel integration. |

### Development Commands

From the `server` directory:

```bash
# Install dependencies
npm install

# Start the development server
npm run dev

# Run the Liveblocks-to-Supabase sync script
npm run sync-comments
```
