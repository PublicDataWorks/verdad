import { createClient } from "@supabase/supabase-js";
import { Liveblocks, stringifyCommentBody } from "@liveblocks/node";
import { liveblocksHeaders } from "./liveblockService";

const supabase = createClient(
  process.env.SUPABASE_URL as string,
  process.env.SUPABASE_SERVICE_ROLE_KEY as string
);

const liveblocks = new Liveblocks({
  secret: process.env.LIVEBLOCKS_SECRET_KEY as string,
});

export async function handleCommentCreated(data: {
  projectId: string;
  roomId: string;
  threadId: string;
  commentId: string;
  createdAt: string;
  createdBy: string;
}) {
  const comment = await liveblocks.getComment({
    roomId: data.roomId,
    threadId: data.threadId,
    commentId: data.commentId,
  });

  if (!comment.body) {
    throw new Error("Comment body is undefined");
  }

  const commentContent = await stringifyCommentBody(comment.body);

  const { error } = await supabase.from("comments").insert({
    comment_id: data.commentId,
    thread_id: data.threadId,
    room_id: data.roomId,
    project_id: data.projectId,
    created_by: data.createdBy,
    body: comment.body,
  });

  if (error) throw error;
  return commentContent;
}

export async function handleCommentEdited(data: {
  projectId: string;
  roomId: string;
  threadId: string;
  commentId: string;
  editedAt: string;
}) {
  const comment = await liveblocks.getComment({
    roomId: data.roomId,
    threadId: data.threadId,
    commentId: data.commentId,
  });

  if (!comment.body) {
    throw new Error("Comment body is undefined");
  }

  const { error } = await supabase
    .from("comments")
    .update({
      edited_at: data.editedAt,
      body: comment.body,
    })
    .eq("comment_id", data.commentId);

  if (error) throw error;
}

export async function handleCommentDeleted(data: {
  commentId: string;
  deletedAt: string;
}) {
  const { error } = await supabase
    .from("comments")
    .update({ deleted_at: data.deletedAt })
    .eq("comment_id", data.commentId);

  if (error) throw error;
}

export async function handleReactionAdded(data: {
  projectId: string;
  roomId: string;
  threadId: string;
  commentId: string;
  emoji: string;
  addedAt: string;
  addedBy: string;
}) {
  const { error } = await supabase.from("comment_reactions").insert({
    comment_id: data.commentId,
    thread_id: data.threadId,
    room_id: data.roomId,
    project_id: data.projectId,
    emoji: data.emoji,
    user_id: data.addedBy,
    added_at: data.addedAt,
  });

  if (error) throw error;
}

export async function handleReactionRemoved(data: {
  projectId: string;
  roomId: string;
  threadId: string;
  commentId: string;
  emoji: string;
  removedAt: string;
  removedBy: string;
}) {
  const { error } = await supabase
    .from("comment_reactions")
    .update({
      removed_at: data.removedAt,
      removed_by: data.removedBy,
    })
    .match({
      comment_id: data.commentId,
      emoji: data.emoji,
      user_id: data.removedBy,
    });

  if (error) throw error;
}

export async function getCommentContent(commentId: string) {
  const { data, error } = await supabase
    .from("comments")
    .select("body")
    .eq("comment_id", commentId)
    .single();

  if (error) {
    console.error("Error fetching comment:", error);
    return null;
  }

  return data;
}

export async function upsertComments(comments: any[]) {
  const { data, error } = await supabase.from("comments").upsert(comments, {
    onConflict: "id",
  });

  if (error) {
    console.error("Error upserting comments:", error);
  }
}

export async function fetchAllRooms(): Promise<any[]> {
  let allRooms: any[] = [];
  let cursor: string | undefined = undefined;
  let hasNextPage = true;

  while (hasNextPage) {
    const response = await liveblocks.getRooms({
      startingAfter: cursor,
      limit: 100,
    });

    allRooms = allRooms.concat(response.data);

    if (response.nextCursor) {
      cursor = response.nextCursor;
    } else {
      hasNextPage = false;
    }
  }

  return allRooms;
}

export async function fetchAllThreads(roomId: string): Promise<any[]> {
  let allThreads: any[] = [];
  let cursor: string | undefined = undefined;
  let hasNextPage = true;

  while (hasNextPage) {
    const response: any = await liveblocks.getThreads({
      roomId,
      limit: 100,
      startingAfter: cursor,
    });

    allThreads = allThreads.concat(response.data);

    if (response.nextCursor) {
      cursor = response.nextCursor;
    } else {
      hasNextPage = false;
    }
  }

  return allThreads;
}

export async function fetchComments(roomId: string, threadId: string) {
  const thread = await liveblocks.getThread({
    roomId,
    threadId,
  });

  return thread.comments || [];
}
