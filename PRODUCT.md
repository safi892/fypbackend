# Code Analyzer

A browser testing workspace for students and developers using the existing C++ analysis backend. Users paste C++ code, choose English or Roman Urdu, and run the model to receive an explanation and commented source without creating an account. Results may request human review; this is not a guarantee of code correctness. The page is served by FastAPI and must work on desktop and mobile without a separate frontend build. Prioritize a clean, modern, easily understood editor and reading experience.

The source language is fixed to C++. Live syntax validation appears below the editor before analysis. Analyze is enabled only for the current validated input. Incomplete syntax remains editable, with an error-line shortcut; a failed validation connection keeps Analyze disabled and offers retry.
