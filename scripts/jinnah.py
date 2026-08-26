import os
import gc
import requests
import img2pdf
from datetime import datetime


# Editions
editions = [
    "karachi",
    "lahore",
    "islamabad"
]


# Today's date
today = datetime.now()

date_url = today.strftime("%d-%m-%Y")
date_name = today.strftime("%d%B")


# Output folder
output = f"Jinnah_Epaper_{date_name}"

os.makedirs(output, exist_ok=True)



def download_edition(edition):

    print("\nStarting:", edition.capitalize())

    temp_folder = os.path.join(output, edition)
    os.makedirs(temp_folder, exist_ok=True)

    images = []

    page = 1


    while True:

        url = f"https://dailyjinnah.com/assets/{edition}/{date_url}/{page}.jpg"


        try:

            response = requests.get(
                url,
                timeout=15
            )


            if response.status_code != 200:

                print(
                    edition.capitalize(),
                    "completed. Total pages:",
                    page-1
                )

                break



            image_path = os.path.join(
                temp_folder,
                f"{page}.jpg"
            )


            with open(image_path, "wb") as f:
                f.write(response.content)



            images.append(image_path)


            print(
                edition.capitalize(),
                "Page",
                page,
                "downloaded"
            )


            page += 1



        except Exception as e:

            print(
                "Error:",
                e
            )

            break




    # Convert JPGs to PDF -- img2pdf seedha file-paths se PDF banata hai,
    # koi bhi image RAM mein RGB decode nahi hoti (pehle yahan sab pages
    # PIL Image ke tor par RAM mein load hote thay, jo "memory quota
    # exceeded" crash ki wajah bunta hai). Ye tareeqa memory-safe hai.

    if images:

        pdf_name = (
            f"Jinnah {edition.capitalize()} {date_name}.pdf"
        )

        pdf_path = os.path.join(
            output,
            pdf_name
        )

        with open(pdf_path, "wb") as f:
            f.write(img2pdf.convert(images))

        print(
            "PDF Created:",
            pdf_name
        )

        gc.collect()

        # Remove images after PDF

        for img in images:

            os.remove(img)

        os.rmdir(temp_folder)




# Run editions one by one

for edition in editions:

    download_edition(edition)



print("\n✅ All Jinnah Editions Completed")