import { v } from "convex/values";
import { internalMutation, internalQuery } from "./_generated/server";

export const byId = internalQuery({
  args: { id: v.id("businesses") },
  handler: async (ctx, { id }) => ctx.db.get(id),
});

export const create = internalMutation({
  args: { name: v.string(), slug: v.string(), vertical: v.optional(v.string()) },
  handler: async (ctx, args) => ctx.db.insert("businesses", args),
});
