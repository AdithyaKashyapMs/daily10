import { NextResponse, type NextRequest } from "next/server";

// Route protection before anything renders: pages for students need the student session cookie,
// faculty pages need the faculty one. The cookies are httpOnly (set by the API), so only their
// presence is checked here; the API validates them and deletes an expired one on its 401, after
// which this sends the user to log in. Names must match daily10/web_session.py.
const STUDENT_COOKIE = "d10_session";
const FACULTY_COOKIE = "d10_faculty";

const STUDENT_PAGES = ["/today", "/progress", "/settings", "/assistant"];

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const has = (name: string) => Boolean(req.cookies.get(name)?.value);
  const to = (path: string) => {
    const url = req.nextUrl.clone();
    url.pathname = path;
    url.search = "";
    return NextResponse.redirect(url);
  };

  if (STUDENT_PAGES.some((p) => pathname === p || pathname.startsWith(p + "/")) && !has(STUDENT_COOKIE)) {
    return to("/auth/student");
  }
  if (pathname.startsWith("/faculty") && !has(FACULTY_COOKIE)) {
    return to("/auth/faculty");
  }
  // Already signed in: skip the login screen (but let a new student finish their profile).
  if (pathname === "/auth/student" && has(STUDENT_COOKIE) && !search.includes("step=profile")) {
    return to("/today");
  }
  if (pathname === "/auth/faculty" && has(FACULTY_COOKIE)) {
    return to("/faculty");
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/today/:path*", "/progress/:path*", "/settings/:path*", "/assistant/:path*", "/faculty/:path*", "/auth/:path*"],
};
