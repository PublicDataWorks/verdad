import {
  fetchAllThreads,
  fetchComments,
  fetchAllRooms,
  upsertComments,
} from "./services/commentService";
import pLimit from "p-limit";

const limit = pLimit(5);

(async () => {
  try {
    console.log("Fetching all rooms...");
    const rooms = await fetchAllRooms();
    console.log(`Found ${rooms.length} rooms.`);

    for (const room of rooms) {
      const roomId = room.id;
      console.log(`Processing room: ${roomId}`);

      console.log(`Fetching threads for room ${roomId}...`);
      const threads = await fetchAllThreads(roomId);
      console.log(`Found ${threads.length} threads in room ${roomId}.`);

      for (const thread of threads) {
        const threadId = thread.id;
        console.log(
          `Fetching comments for thread ${threadId} in room ${roomId}...`
        );
        const comments = await fetchComments(roomId, threadId);
        console.log(
          `Thread ${threadId} in room ${roomId} has ${comments.length} comments.`
        );

        if (comments.length > 0) {
          const transformedComments = comments.map((comment) => ({
            id: comment.id,
            thread_id: threadId,
            room_id: roomId,
            created_by: comment.userId,
            body: JSON.stringify(comment.body),
            comment_at: comment.createdAt,
          }));

          const chunkSize = 100;
          const chunks = [];
          for (let i = 0; i < transformedComments.length; i += chunkSize) {
            chunks.push(transformedComments.slice(i, i + chunkSize));
          }

          for (const chunk of chunks) {
            await limit(() => upsertComments(chunk));
          }
        }
      }
    }

    console.log("All comments from all rooms have been synced.");
  } catch (error) {
    console.error("An error occurred:", error);
  }
})();
