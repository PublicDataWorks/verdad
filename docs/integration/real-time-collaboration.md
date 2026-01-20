# Real-time Collaboration

## Real-time Collaboration

VERDAD facilitates collaborative analysis by allowing journalists and researchers to review flagged audio snippets together in real-time. This functionality is powered by [Liveblocks](https://liveblocks.io/), providing features like threaded comments, emoji reactions, and live presence indicators.

### Overview

Every audio snippet identified by the AI pipeline is treated as a unique "Room" in the collaboration layer. Within these rooms, users can:
*   **Discuss findings:** Post comments and reply to threads.
*   **Vote and React:** Use emoji reactions to indicate agreement or flag specific content.
*   **Mention Peers:** Tag other researchers to draw attention to specific evidence.
*   **Review AI Labels:** Upvote existing AI-generated labels or add custom ones.

### Authentication

The frontend interacts with a secure authentication endpoint to grant users access to specific snippet rooms.

**Endpoint:** `POST /api/liveblocks-auth`

This endpoint handles the handshake between the user session and the Liveblocks servers, ensuring that only authorized researchers can view or participate in the discussion of specific datasets.

### Commenting and Feedback

The collaboration system supports rich interaction through the following capabilities:

*   **Threaded Discussions:** Comments are organized into threads to keep conversations focused on specific claims or audio segments.
*   **Mentions:** Users can `@mention` colleagues. When a mention occurs, the system triggers a notification workflow.
*   **Reactions:** Support for adding and removing emoji reactions to comments for quick sentiment gathering.

### Data Persistence and Sync

While Liveblocks manages the real-time state, VERDAD maintains a persistent record of all collaborative activity in its Postgres database (via Supabase). This ensures that human feedback can be used to improve future AI heuristics.

#### Webhook Integration
The server listens for Liveblocks webhooks to sync activity back to the primary database:

**Endpoint:** `POST /api/webhooks/liveblocks`

| Event Type | Action |
| :--- | :--- |
| `comment_created` | Persists the comment body and metadata to the `comments` table. |
| `comment_edited` | Updates the existing record and tracks the `edited_at` timestamp. |
| `comment_deleted` | Marks the comment as deleted in the database. |
| `reaction_added` | Records the emoji and user ID in the `comment_reactions` table. |

#### Manual Sync Utility
For administrative purposes or disaster recovery, the system includes a background service to batch-sync all rooms and threads.
```typescript
// Internal usage for syncing all Liveblocks data to the local database
import { fetchAllRooms, fetchAllThreads, fetchComments } from "./services/commentService";

// This process iterates through all active rooms and upserts 
// comments and reactions to ensure data integrity.
```

### Notifications

To keep researchers engaged, VERDAD sends notifications for critical collaborative events.

#### Slack Integration
If configured via the `SLACK_NOTIFICATION_EMAIL` environment variable, the system sends formatted alerts to a Slack channel.
*   **Mentions:** Notifies a user they have been tagged.
*   **New Comments:** Alerts the team to new activity on a snippet.
*   **Edits:** Provides a "diff" view showing original vs. edited content.

#### Email Notifications
Powered by **Resend**, the system sends HTML-formatted emails for mentions and significant updates using customizable templates stored in the database.

| Template Name | Usage |
| :--- | :--- |
| `mention_notification` | Sent when a user is tagged in a room. |
| `comment_notification` | Sent when new activity occurs in a followed thread. |

### Configuration

To enable these features, ensure the following environment variables are set in the server environment:

```bash
LIVEBLOCKS_SECRET_KEY=sk_prod_...
RESEND_API_KEY=re_...
SLACK_NOTIFICATION_EMAIL=your-slack-inbound-email@example.com
```
