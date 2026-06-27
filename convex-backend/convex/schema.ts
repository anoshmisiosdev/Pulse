import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

// Multi-tenant auth store. Each business is a tenant; users belong to one.
export default defineSchema({
  businesses: defineTable({
    name: v.string(),
    slug: v.string(),
    vertical: v.optional(v.string()),
  }).index("by_slug", ["slug"]),

  users: defineTable({
    email: v.string(),
    passwordHash: v.string(),
    salt: v.string(),
    businessId: v.id("businesses"),
    role: v.string(),
  }).index("by_email", ["email"]),
});
