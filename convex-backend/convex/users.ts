import { v } from "convex/values";
import { internalMutation, internalQuery } from "./_generated/server";

export const byEmail = internalQuery({
  args: { email: v.string() },
  handler: async (ctx, { email }) =>
    ctx.db
      .query("users")
      .withIndex("by_email", (q) => q.eq("email", email))
      .unique(),
});

export const create = internalMutation({
  args: {
    email: v.string(),
    passwordHash: v.string(),
    salt: v.string(),
    businessId: v.id("businesses"),
    role: v.string(),
  },
  handler: async (ctx, args) => ctx.db.insert("users", args),
});
