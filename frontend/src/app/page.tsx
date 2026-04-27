export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <h1 className="text-4xl font-bold mb-4">NukeLab Platform v2.0</h1>
      <p className="text-lg text-gray-600">Multi-user scientific computing platform</p>
      <div className="mt-8 space-x-4">
        <a
          href="/login"
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          Login
        </a>
        <a
          href="/api/docs"
          className="px-4 py-2 bg-gray-200 text-gray-800 rounded hover:bg-gray-300"
        >
          API Docs
        </a>
      </div>
    </main>
  );
}
